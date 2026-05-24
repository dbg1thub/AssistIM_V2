"""Store profile regions as ISO country and subdivision codes."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.services.region_catalog import RegionCatalog


revision = "20260524_0026"
down_revision = "20260524_0025"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "users" not in set(sa.inspect(bind).get_table_names()):
        return

    columns = _column_names(bind, "users")
    if "region_country_code" not in columns:
        op.add_column("users", sa.Column("region_country_code", sa.String(length=2), nullable=True))
    if "region_subdivision_code" not in columns:
        op.add_column("users", sa.Column("region_subdivision_code", sa.String(length=16), nullable=True))

    columns = _column_names(bind, "users")
    if "region" not in columns:
        return

    catalog = RegionCatalog()
    rows = bind.execute(sa.text("SELECT id, region FROM users WHERE region IS NOT NULL AND TRIM(region) <> ''")).mappings().all()
    for row in rows:
        country_code, subdivision_code = catalog.match_legacy_region_text(row["region"])
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET region_country_code = :country_code,
                    region_subdivision_code = :subdivision_code,
                    region = NULL
                WHERE id = :user_id
                """
            ),
            {
                "country_code": country_code,
                "subdivision_code": subdivision_code,
                "user_id": row["id"],
            },
        )


def downgrade() -> None:
    return None
