from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    AdminBinding,
    Domain,
    Group,
    GroupSettings,
    ModerationEvent,
    PendingReview,
    TrainingExample,
    TrustedUser,
    User,
    UserViolation,
)


def get_or_create_user(session: Session, telegram_user: Any) -> User:
    telegram_user_id = int(getattr(telegram_user, "id", telegram_user))
    user = session.scalar(select(User).where(User.telegram_user_id == telegram_user_id))
    if user:
        user.username = getattr(telegram_user, "username", user.username)
        user.first_name = getattr(telegram_user, "first_name", user.first_name)
        user.last_name = getattr(telegram_user, "last_name", user.last_name)
        return user
    user = User(
        telegram_user_id=telegram_user_id,
        username=getattr(telegram_user, "username", None),
        first_name=getattr(telegram_user, "first_name", None),
        last_name=getattr(telegram_user, "last_name", None),
    )
    session.add(user)
    session.flush()
    return user


def get_or_create_group(
    session: Session,
    telegram_chat_id: int,
    title: str | None,
    chat_type: str,
    settings: Settings,
) -> Group:
    group = session.scalar(select(Group).where(Group.telegram_chat_id == telegram_chat_id))
    if group is None:
        group = Group(
            telegram_chat_id=telegram_chat_id,
            title=title,
            type=chat_type,
            authorized=settings.chat_is_allowlisted(telegram_chat_id),
        )
        session.add(group)
        session.flush()
    else:
        group.title = title or group.title
        group.type = chat_type or group.type
        if settings.chat_is_allowlisted(telegram_chat_id):
            group.authorized = True
    get_or_create_group_settings(session, group, settings)
    return group


def get_or_create_group_settings(
    session: Session, group: Group, settings: Settings
) -> GroupSettings:
    group_settings = session.scalar(
        select(GroupSettings).where(GroupSettings.group_id == group.id)
    )
    if group_settings:
        return group_settings
    group_settings = GroupSettings(
        group_id=group.id,
        mode=settings.default_group_mode,
        spam_delete_threshold=settings.spam_delete_threshold,
        spam_ban_threshold=settings.spam_ban_threshold,
        suspicious_low_threshold=settings.suspicious_low_threshold,
        suspicious_high_threshold=settings.suspicious_high_threshold,
        notify_admin_user_id=settings.default_notify_admin_id,
        ai_scan_all_messages=settings.ai_scan_all_messages,
        ai_scan_links_only=settings.ai_scan_links_only,
    )
    session.add(group_settings)
    session.flush()
    return group_settings


def mark_group_authorized(session: Session, group: Group) -> None:
    group.authorized = True
    session.flush()


def chat_is_authorized(group: Group | None, settings: Settings) -> bool:
    if not settings.require_authorized_chats:
        return True
    if group is None:
        return False
    return bool(group.authorized or settings.chat_is_allowlisted(group.telegram_chat_id))


def setup_is_allowed_for_user(
    group: Group, telegram_user_id: int | None, settings: Settings
) -> bool:
    if chat_is_authorized(group, settings):
        return True
    return settings.user_is_owner_admin(telegram_user_id)


def bind_admin(
    session: Session,
    group_id: int,
    admin_user_id: int,
    can_receive_notifications: bool = True,
) -> AdminBinding:
    binding = session.scalar(
        select(AdminBinding).where(
            AdminBinding.group_id == group_id,
            AdminBinding.admin_user_id == admin_user_id,
        )
    )
    if binding is None:
        binding = AdminBinding(
            group_id=group_id,
            admin_user_id=admin_user_id,
            can_receive_notifications=can_receive_notifications,
        )
        session.add(binding)
    else:
        binding.can_receive_notifications = can_receive_notifications
    session.flush()
    return binding


def is_trusted_user(session: Session, group_id: int, telegram_user_id: int | None) -> bool:
    if telegram_user_id is None:
        return False
    return (
        session.scalar(
            select(TrustedUser.id).where(
                TrustedUser.group_id == group_id,
                TrustedUser.telegram_user_id == telegram_user_id,
            )
        )
        is not None
    )


def trust_user(
    session: Session,
    group_id: int,
    telegram_user_id: int,
    admin_user_id: int,
    reason: str | None = None,
) -> TrustedUser:
    trusted = session.scalar(
        select(TrustedUser).where(
            TrustedUser.group_id == group_id,
            TrustedUser.telegram_user_id == telegram_user_id,
        )
    )
    if trusted is None:
        trusted = TrustedUser(
            group_id=group_id,
            telegram_user_id=telegram_user_id,
            trusted_by_admin_id=admin_user_id,
            reason=reason,
        )
        session.add(trusted)
    else:
        trusted.trusted_by_admin_id = admin_user_id
        trusted.reason = reason or trusted.reason
    session.flush()
    return trusted


def untrust_user(session: Session, group_id: int, telegram_user_id: int) -> None:
    session.execute(
        delete(TrustedUser).where(
            TrustedUser.group_id == group_id,
            TrustedUser.telegram_user_id == telegram_user_id,
        )
    )


def set_domain_status(
    session: Session, group_id: int, domain: str, status: str, admin_user_id: int
) -> Domain:
    clean_domain = domain.lower().strip()
    record = session.scalar(
        select(Domain).where(Domain.group_id == group_id, Domain.domain == clean_domain)
    )
    if record is None:
        record = Domain(
            group_id=group_id,
            domain=clean_domain,
            status=status,
            created_by_admin_id=admin_user_id,
        )
        session.add(record)
    else:
        record.status = status
        record.created_by_admin_id = admin_user_id
    session.flush()
    return record


def get_domain_statuses(
    session: Session, group_id: int, domains: list[str]
) -> dict[str, str]:
    if not domains:
        return {}
    records = session.scalars(
        select(Domain).where(
            Domain.group_id == group_id,
            Domain.domain.in_([domain.lower() for domain in domains]),
        )
    ).all()
    return {record.domain: record.status for record in records}


def save_training_example(
    session: Session,
    *,
    group_id: int | None,
    label: str,
    normalized_text: str,
    raw_excerpt: str,
    text_hash: str,
    domains: list[str],
    telegram_links: list[str],
    features: dict[str, Any],
    source: str,
    created_by_admin_id: int | None,
    global_allowed: bool = False,
    embedding: list[float] | None = None,
) -> TrainingExample:
    example = TrainingExample(
        group_id=group_id,
        label=label,
        normalized_text=normalized_text,
        raw_excerpt=raw_excerpt,
        text_hash=text_hash,
        domains=domains,
        telegram_links=telegram_links,
        features=features,
        embedding=embedding,
        source=source,
        created_by_admin_id=created_by_admin_id,
        global_allowed=global_allowed,
    )
    session.add(example)
    session.flush()
    return example


def find_exact_training_example(
    session: Session, group_id: int, text_hash: str
) -> TrainingExample | None:
    return session.scalar(
        select(TrainingExample).where(
            TrainingExample.text_hash == text_hash,
            or_(TrainingExample.group_id == group_id, TrainingExample.global_allowed.is_(True)),
        )
    )


def list_relevant_examples(
    session: Session,
    *,
    group_id: int,
    normalized_text: str,
    label: str,
    limit: int = 4,
    global_enabled: bool = False,
) -> list[TrainingExample]:
    words = {w for w in normalized_text.lower().split() if len(w) > 3}
    candidates = session.scalars(
        select(TrainingExample)
        .where(
            TrainingExample.label == label,
            or_(
                TrainingExample.group_id == group_id,
                and_(TrainingExample.global_allowed.is_(True), global_enabled),
            ),
        )
        .order_by(TrainingExample.created_at.desc())
        .limit(100)
    ).all()
    scored: list[tuple[int, TrainingExample]] = []
    for candidate in candidates:
        candidate_words = set(candidate.normalized_text.lower().split())
        scored.append((len(words & candidate_words), candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in scored[:limit]]


def save_moderation_event(
    session: Session,
    *,
    group_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    sender_user_id: int | None,
    normalized_text: str,
    text_hash: str,
    domains: list[str],
    ai_label: str | None,
    ai_confidence: float | None,
    rule_score: float,
    final_score: float,
    action_taken: str,
    action_status: str,
    reasons: list[str],
    provider_name: str | None,
    model_name: str | None,
    prompt_version: str | None,
    provider_error: str | None = None,
) -> ModerationEvent:
    event = ModerationEvent(
        group_id=group_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        sender_user_id=sender_user_id,
        normalized_text=normalized_text,
        text_hash=text_hash,
        domains=domains,
        ai_label=ai_label,
        ai_confidence=ai_confidence,
        rule_score=rule_score,
        final_score=final_score,
        action_taken=action_taken,
        action_status=action_status,
        reasons=reasons,
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=prompt_version,
        provider_error=provider_error,
    )
    session.add(event)
    session.flush()
    return event


def create_pending_review(
    session: Session,
    *,
    moderation_event_id: int,
    admin_user_id: int,
    callback_token: str,
    ttl_days: int = 7,
) -> PendingReview:
    review = PendingReview(
        moderation_event_id=moderation_event_id,
        admin_user_id=admin_user_id,
        callback_token=callback_token,
        expires_at=datetime.now(tz=UTC) + timedelta(days=ttl_days),
    )
    session.add(review)
    session.flush()
    return review


def get_pending_review(session: Session, token: str) -> PendingReview | None:
    return session.scalar(
        select(PendingReview).where(
            PendingReview.callback_token == token,
            PendingReview.status == "pending",
            PendingReview.expires_at > datetime.now(tz=UTC),
        )
    )


def record_violation(
    session: Session,
    *,
    group_id: int,
    telegram_user_id: int,
    action: str,
    score: float,
) -> UserViolation:
    violation = session.scalar(
        select(UserViolation).where(
            UserViolation.group_id == group_id,
            UserViolation.telegram_user_id == telegram_user_id,
        )
    )
    if violation is None:
        violation = UserViolation(
            group_id=group_id,
            telegram_user_id=telegram_user_id,
            violation_count=0,
        )
        session.add(violation)
    violation.violation_count += 1
    violation.last_violation_at = datetime.now(tz=UTC)
    violation.last_action = action
    violation.risk_score = max(violation.risk_score, score)
    session.flush()
    return violation


def get_violation_score(
    session: Session, group_id: int, telegram_user_id: int | None
) -> float:
    if telegram_user_id is None:
        return 0.0
    violation = session.scalar(
        select(UserViolation).where(
            UserViolation.group_id == group_id,
            UserViolation.telegram_user_id == telegram_user_id,
        )
    )
    if violation is None:
        return 0.0
    return min(0.20, violation.violation_count * 0.04 + violation.risk_score * 0.12)


def count_examples(session: Session, group_id: int) -> dict[str, int]:
    rows = session.execute(
        select(TrainingExample.label, func.count(TrainingExample.id))
        .where(TrainingExample.group_id == group_id)
        .group_by(TrainingExample.label)
    ).all()
    counts = {"spam": 0, "not_spam": 0}
    counts.update({label: count for label, count in rows})
    return counts


def forget_group_data(session: Session, group_id: int) -> None:
    event_ids = select(ModerationEvent.id).where(ModerationEvent.group_id == group_id)
    session.execute(delete(PendingReview).where(PendingReview.moderation_event_id.in_(event_ids)))
    for model in (
        ModerationEvent,
        UserViolation,
        TrainingExample,
        TrustedUser,
        Domain,
        AdminBinding,
        GroupSettings,
    ):
        session.execute(delete(model).where(model.group_id == group_id))
    session.execute(delete(Group).where(Group.id == group_id))
