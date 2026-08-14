"""Add support console tables.

Revision ID: 0002_support_console
Revises: 0001_initial
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_support_console"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger()),
        sa.Column("issue_type", sa.String(length=32), nullable=False),
        sa.Column("title_query", sa.String(length=255)),
        sa.Column("category_hint", sa.String(length=20)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("matched_show_id", sa.Integer()),
        sa.Column("matched_title", sa.String(length=255)),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "support_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger()),
        sa.Column("title_query", sa.String(length=255), nullable=False),
        sa.Column("category_hint", sa.String(length=20)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("matched_show_id", sa.Integer()),
        sa.Column("matched_title", sa.String(length=255)),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "tutorial_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("caption", sa.Text()),
        sa.Column("source_chat_id", sa.BigInteger()),
        sa.Column("source_message_id", sa.BigInteger()),
        sa.Column("created_by_admin_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("label"),
    )
    op.create_table(
        "bot_sent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    for table, columns in {
        "support_issues": [
            "group_id",
            "telegram_chat_id",
            "telegram_message_id",
            "sender_user_id",
            "issue_type",
            "title_query",
            "category_hint",
            "status",
        ],
        "support_requests": [
            "group_id",
            "telegram_chat_id",
            "telegram_message_id",
            "sender_user_id",
            "title_query",
            "category_hint",
            "status",
        ],
        "tutorial_assets": ["label"],
        "bot_sent_messages": ["chat_id", "message_id", "purpose", "delete_after"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in [
        "bot_sent_messages",
        "tutorial_assets",
        "support_requests",
        "support_issues",
    ]:
        op.drop_table(table)
