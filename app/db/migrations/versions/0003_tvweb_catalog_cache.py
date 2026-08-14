"""Add tvweb catalog cache tables.

Revision ID: 0003_tvweb_catalog_cache
Revises: 0002_support_console
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_tvweb_catalog_cache"
down_revision = "0002_support_console"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tvweb_catalog_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tvweb_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("title_key", sa.String(length=255), nullable=False),
        sa.Column("episode_title", sa.String(length=255)),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("slug", sa.String(length=512), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("rating", sa.Float()),
        sa.Column("download_link", sa.Text()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tvweb_id"),
    )
    op.create_table(
        "tvweb_catalog_sync",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True)),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("label"),
    )
    for table, columns in {
        "tvweb_catalog_items": ["tvweb_id", "title", "title_key", "category", "slug"],
        "tvweb_catalog_sync": ["label"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("tvweb_catalog_sync")
    op.drop_table("tvweb_catalog_items")
