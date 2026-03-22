"""Schema compatibility helpers for environments without Alembic upgrades applied."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, Connection


USER_PROFILE_COLUMN_DDL: dict[str, str] = {
    "email": "VARCHAR(255)",
    "phone": "VARCHAR(32)",
    "birthday": "DATE",
    "region": "VARCHAR(128)",
    "signature": "TEXT",
    "gender": "VARCHAR(32)",
}

USER_PROFILE_INDEX_DDL: dict[str, str] = {
    "idx_users_email": "CREATE INDEX IF NOT EXISTS idx_users_email ON users (email)",
    "idx_users_phone": "CREATE INDEX IF NOT EXISTS idx_users_phone ON users (phone)",
}


def _get_table_names(bind: Engine | Connection) -> set[str]:
    return set(inspect(bind).get_table_names())


def _get_column_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table_name)}


def _get_index_names(bind: Engine | Connection, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(bind).get_indexes(table_name)}


def ensure_schema_compatibility(engine: Engine) -> list[str]:
    """Apply lightweight idempotent schema fixes for known legacy drift."""
    applied: list[str] = []

    if "users" not in _get_table_names(engine):
        return applied

    with engine.begin() as connection:
        columns = _get_column_names(connection, "users")
        for column_name, ddl in USER_PROFILE_COLUMN_DDL.items():
            if column_name in columns:
                continue
            connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {ddl}"))
            applied.append(f"users.{column_name}")
            columns.add(column_name)

        indexes = _get_index_names(connection, "users")
        for index_name, ddl in USER_PROFILE_INDEX_DDL.items():
            if index_name in indexes:
                continue
            connection.execute(text(ddl))
            applied.append(index_name)
            indexes.add(index_name)

    return applied


def describe_schema_compatibility(applied: Iterable[str]) -> str:
    items = list(applied)
    if not items:
        return "Schema compatibility already up to date."
    return "Applied schema compatibility updates: " + ", ".join(items)
