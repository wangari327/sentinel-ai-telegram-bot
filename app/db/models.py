from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    pass


JsonType = JSON().with_variant(JSONB, "postgresql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    type: Mapped[str] = mapped_column(String(32), default="supergroup")
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    settings: Mapped[GroupSettings] = relationship(
        back_populates="group", cascade="all, delete-orphan", uselist=False
    )


class GroupSettings(TimestampMixin, Base):
    __tablename__ = "group_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), unique=True, index=True
    )
    mode: Mapped[str] = mapped_column(String(32), default="monitor_only")
    auto_delete_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    silent_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ban_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    scan_admins: Mapped[bool] = mapped_column(Boolean, default=False)
    global_training_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_scan_all_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_scan_links_only: Mapped[bool] = mapped_column(Boolean, default=True)
    spam_delete_threshold: Mapped[float] = mapped_column(Float, default=0.88)
    spam_ban_threshold: Mapped[float] = mapped_column(Float, default=0.96)
    suspicious_low_threshold: Mapped[float] = mapped_column(Float, default=0.55)
    suspicious_high_threshold: Mapped[float] = mapped_column(Float, default=0.87)
    notify_admin_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    group: Mapped[Group] = relationship(back_populates="settings")


class TrustedUser(Base):
    __tablename__ = "trusted_users"
    __table_args__ = (UniqueConstraint("group_id", "telegram_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    trusted_by_admin_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (UniqueConstraint("group_id", "domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(16))
    created_by_admin_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class TrainingExample(Base):
    __tablename__ = "training_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    label: Mapped[str] = mapped_column(String(16), index=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    raw_excerpt: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    domains: Mapped[list[str]] = mapped_column(JsonType, default=list)
    telegram_links: Mapped[list[str]] = mapped_column(JsonType, default=list)
    features: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(JsonType, nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    created_by_admin_id: Mapped[int | None] = mapped_column(BigInteger)
    global_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    normalized_text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    domains: Mapped[list[str]] = mapped_column(JsonType, default=list)
    ai_label: Mapped[str | None] = mapped_column(String(32))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    rule_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    action_taken: Mapped[str] = mapped_column(String(64), default="allow")
    action_status: Mapped[str] = mapped_column(String(64), default="pending")
    reasons: Mapped[list[str]] = mapped_column(JsonType, default=list)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(BigInteger)
    review_result: Mapped[str | None] = mapped_column(String(64))
    provider_name: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    provider_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False, index=True
    )


class UserViolation(Base):
    __tablename__ = "user_violations"
    __table_args__ = (UniqueConstraint("group_id", "telegram_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    violation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_violation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action: Mapped[str | None] = mapped_column(String(64))
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)


class AdminBinding(Base):
    __tablename__ = "admin_bindings"
    __table_args__ = (UniqueConstraint("group_id", "admin_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    can_receive_notifications: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class PendingReview(Base):
    __tablename__ = "pending_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    moderation_event_id: Mapped[int] = mapped_column(
        ForeignKey("moderation_events.id", ondelete="CASCADE"), index=True
    )
    admin_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    callback_token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SupportIssue(TimestampMixin, Base):
    __tablename__ = "support_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    issue_type: Mapped[str] = mapped_column(String(32), index=True)
    title_query: Mapped[str | None] = mapped_column(String(255), index=True)
    category_hint: Mapped[str | None] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    matched_show_id: Mapped[int | None] = mapped_column(Integer)
    matched_title: Mapped[str | None] = mapped_column(String(255))
    normalized_text: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)


class SupportRequest(TimestampMixin, Base):
    __tablename__ = "support_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    sender_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    title_query: Mapped[str] = mapped_column(String(255), index=True)
    category_hint: Mapped[str | None] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    matched_show_id: Mapped[int | None] = mapped_column(Integer)
    matched_title: Mapped[str | None] = mapped_column(String(255))
    normalized_text: Mapped[str] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)


class TvwebCatalogItem(TimestampMixin, Base):
    __tablename__ = "tvweb_catalog_items"
    __table_args__ = (UniqueConstraint("tvweb_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tvweb_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    title_key: Mapped[str] = mapped_column(String(255), index=True)
    episode_title: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32), index=True)
    slug: Mapped[str] = mapped_column(String(512), index=True)
    year: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    download_link: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TvwebCatalogSync(TimestampMixin, Base):
    __tablename__ = "tvweb_catalog_sync"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class TutorialAsset(TimestampMixin, Base):
    __tablename__ = "tutorial_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    file_id: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(32))
    caption: Mapped[str | None] = mapped_column(Text)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_admin_id: Mapped[int | None] = mapped_column(BigInteger)


class BotSentMessage(Base):
    __tablename__ = "bot_sent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    purpose: Mapped[str] = mapped_column(String(64), index=True)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
