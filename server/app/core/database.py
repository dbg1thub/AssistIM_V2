"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.core.schema_compat import describe_schema_compatibility, ensure_schema_compatibility


class Base(DeclarativeBase):
    """Base declarative model."""


SessionLocal = sessionmaker(
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)

_engine: Engine | None = None
_engine_signature: tuple[str, bool] | None = None


def _connect_args_for_database_url(database_url: str) -> dict[str, object]:
    """Return SQLAlchemy connect args for one database URL."""
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _engine_signature_for(settings: Settings) -> tuple[str, bool]:
    """Return one stable signature for the current engine configuration."""
    return settings.database_url, settings.debug


def configure_database(settings: Settings | None = None) -> Engine:
    """Configure the process-global engine and session factory from one settings snapshot."""
    global _engine, _engine_signature

    current_settings = settings or get_settings()
    target_signature = _engine_signature_for(current_settings)
    if _engine is not None and _engine_signature == target_signature:
        return _engine

    previous_engine = _engine
    engine = create_engine(
        current_settings.database_url,
        echo=current_settings.debug,
        future=True,
        connect_args=_connect_args_for_database_url(current_settings.database_url),
    )
    SessionLocal.configure(bind=engine)
    _engine = engine
    _engine_signature = target_signature

    if previous_engine is not None and previous_engine is not engine:
        previous_engine.dispose()

    return engine


def get_engine() -> Engine:
    """Return the currently configured engine, creating it lazily if needed."""
    return configure_database()


def get_db() -> Generator[Session, None, None]:
    """Provide a request-scoped database session."""
    configure_database()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(settings: Settings | None = None) -> None:
    """Create database tables and apply lightweight compatibility upgrades."""
    from app.models import file, group, message, moment, session, user  # noqa: F401

    engine = configure_database(settings)
    Base.metadata.create_all(bind=engine)
    applied = ensure_schema_compatibility(engine)
    if applied:
        logger.warning(describe_schema_compatibility(applied))
