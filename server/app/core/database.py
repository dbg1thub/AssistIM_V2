"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect
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
RUNTIME_SCHEMA_REQUIRED_TABLES = frozenset(
    {
        "users",
        "messages",
        "sessions",
        "session_members",
        "files",
        "session_events",
    }
)


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


def _missing_runtime_schema_tables(engine: Engine) -> set[str]:
    """Return required runtime tables that are still missing."""
    return set(RUNTIME_SCHEMA_REQUIRED_TABLES) - set(inspect(engine).get_table_names())


def init_db(settings: Settings | None = None) -> None:
    """Validate runtime schema presence and apply fallback-only compatibility upgrades."""
    from app.models import file, group, message, moment, session, user  # noqa: F401

    engine = configure_database(settings)
    missing_tables = _missing_runtime_schema_tables(engine)
    if missing_tables:
        missing_list = ", ".join(sorted(missing_tables))
        raise RuntimeError(
            "Database schema is not initialized for runtime use. "
            "Run `alembic upgrade head` before starting the API. "
            f"Missing tables: {missing_list}"
        )
    applied = ensure_schema_compatibility(engine)
    if applied:
        logger.warning(describe_schema_compatibility(applied))
