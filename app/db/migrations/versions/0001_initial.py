"""Initial SentinelAI schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255)),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("last_name", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"])
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=512)),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("setup_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authorized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_chat_id"),
    )
    op.create_index("ix_groups_telegram_chat_id", "groups", ["telegram_chat_id"])
    op.create_table(
        "group_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("auto_delete_enabled", sa.Boolean(), nullable=False),
        sa.Column("silent_enabled", sa.Boolean(), nullable=False),
        sa.Column("ban_enabled", sa.Boolean(), nullable=False),
        sa.Column("scan_admins", sa.Boolean(), nullable=False),
        sa.Column("global_training_enabled", sa.Boolean(), nullable=False),
        sa.Column("ai_scan_all_messages", sa.Boolean(), nullable=False),
        sa.Column("ai_scan_links_only", sa.Boolean(), nullable=False),
        sa.Column("spam_delete_threshold", sa.Float(), nullable=False),
        sa.Column("spam_ban_threshold", sa.Float(), nullable=False),
        sa.Column("suspicious_low_threshold", sa.Float(), nullable=False),
        sa.Column("suspicious_high_threshold", sa.Float(), nullable=False),
        sa.Column("notify_admin_user_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id"),
    )
    for table, columns in {
        "trusted_users": [
            sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
            sa.Column("trusted_by_admin_id", sa.BigInteger(), nullable=False),
            sa.Column("reason", sa.Text()),
        ],
        "domains": [
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_by_admin_id", sa.BigInteger(), nullable=False),
        ],
    }.items():
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
            *columns,
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    op.create_unique_constraint("uq_trusted_users_group_user", "trusted_users", ["group_id", "telegram_user_id"])
    op.create_unique_constraint("uq_domains_group_domain", "domains", ["group_id", "domain"])
    op.create_table(
        "training_examples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE")),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("raw_excerpt", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("telegram_links", sa.JSON(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON()),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("created_by_admin_id", sa.BigInteger()),
        sa.Column("global_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "moderation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_user_id", sa.BigInteger()),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("domains", sa.JSON(), nullable=False),
        sa.Column("ai_label", sa.String(length=32)),
        sa.Column("ai_confidence", sa.Float()),
        sa.Column("rule_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("action_taken", sa.String(length=64), nullable=False),
        sa.Column("action_status", sa.String(length=64), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("reviewed_by_admin_id", sa.BigInteger()),
        sa.Column("review_result", sa.String(length=64)),
        sa.Column("provider_name", sa.String(length=64)),
        sa.Column("model_name", sa.String(length=128)),
        sa.Column("prompt_version", sa.String(length=64)),
        sa.Column("provider_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_violations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("violation_count", sa.Integer(), nullable=False),
        sa.Column("last_violation_at", sa.DateTime(timezone=True)),
        sa.Column("last_action", sa.String(length=64)),
        sa.Column("risk_score", sa.Float(), nullable=False),
    )
    op.create_unique_constraint("uq_user_violations_group_user", "user_violations", ["group_id", "telegram_user_id"])
    op.create_table(
        "admin_bindings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
        sa.Column("can_receive_notifications", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_unique_constraint("uq_admin_bindings_group_admin", "admin_bindings", ["group_id", "admin_user_id"])
    op.create_table(
        "pending_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("moderation_event_id", sa.Integer(), sa.ForeignKey("moderation_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=False),
        sa.Column("callback_token", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("callback_token"),
    )


def downgrade() -> None:
    for table in [
        "pending_reviews",
        "admin_bindings",
        "user_violations",
        "moderation_events",
        "training_examples",
        "domains",
        "trusted_users",
        "group_settings",
        "groups",
        "users",
    ]:
        op.drop_table(table)
