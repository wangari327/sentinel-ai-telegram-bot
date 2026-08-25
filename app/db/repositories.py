from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    AdminBinding,
    BotSentMessage,
    Domain,
    Group,
    GroupSettings,
    ModerationEvent,
    PendingReview,
    SupportIssue,
    SupportRequest,
    TrainingExample,
    TrustedUser,
    TutorialAsset,
    TvwebCatalogItem,
    TvwebCatalogSync,
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
    group_settings = session.scalar(select(GroupSettings).where(GroupSettings.group_id == group.id))
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


def get_domain_statuses(session: Session, group_id: int, domains: list[str]) -> dict[str, str]:
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
    violation.risk_score = max(violation.risk_score or 0.0, score)
    session.flush()
    return violation


def get_violation_score(session: Session, group_id: int, telegram_user_id: int | None) -> float:
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


def get_violation_count(session: Session, group_id: int, telegram_user_id: int | None) -> int:
    if telegram_user_id is None:
        return 0
    violation = session.scalar(
        select(UserViolation).where(
            UserViolation.group_id == group_id,
            UserViolation.telegram_user_id == telegram_user_id,
        )
    )
    return int(violation.violation_count) if violation is not None else 0


def count_examples(session: Session, group_id: int) -> dict[str, int]:
    rows = session.execute(
        select(TrainingExample.label, func.count(TrainingExample.id))
        .where(TrainingExample.group_id == group_id)
        .group_by(TrainingExample.label)
    ).all()
    counts = {"spam": 0, "not_spam": 0}
    counts.update({label: count for label, count in rows})
    return counts


def count_moderation_events(session: Session, group_id: int) -> int:
    return int(
        session.scalar(
            select(func.count(ModerationEvent.id)).where(ModerationEvent.group_id == group_id)
        )
        or 0
    )


def list_recent_moderation_events(
    session: Session,
    group_id: int | None = None,
    *,
    limit: int = 10,
) -> list[ModerationEvent]:
    query = select(ModerationEvent).order_by(ModerationEvent.created_at.desc()).limit(limit)
    if group_id is not None:
        query = query.where(ModerationEvent.group_id == group_id)
    return list(session.scalars(query).all())


def list_recent_reviewable_moderation_events(
    session: Session,
    group_id: int | None = None,
    *,
    limit: int = 10,
    candidate_limit: int = 250,
) -> list[ModerationEvent]:
    query = (
        select(ModerationEvent)
        .order_by(ModerationEvent.created_at.desc())
        .limit(max(candidate_limit, limit))
    )
    if group_id is not None:
        query = query.where(ModerationEvent.group_id == group_id)
    candidates = session.scalars(query).all()
    return [event for event in candidates if moderation_event_is_reviewable(event)][:limit]


def moderation_event_is_reviewable(event: ModerationEvent) -> bool:
    action = (event.action_taken or "").casefold()
    text_reviewable = _event_text_is_reviewable(event.normalized_text or "")
    reasons_reviewable = _event_reasons_are_reviewable(event.reasons or [])
    if action in {"monitor_setup_required", "monitor"} and not (
        (event.final_score or 0.0) >= 0.55
        or (event.rule_score or 0.0) >= 0.25
        or reasons_reviewable
        or text_reviewable
    ):
        return False
    if action in {
        "ask_admin",
        "delete",
        "delete_after_review",
        "delete_and_ban",
        "delete_pending_review",
    }:
        return True
    if event.review_result:
        return event.review_result not in {"not_spam", "good", "good_example"}
    label = (event.ai_label or "").casefold()
    if label in {"spam", "suspicious"} and (event.ai_confidence or 0.0) >= 0.55:
        return True
    if (event.final_score or 0.0) >= 0.55 or (event.rule_score or 0.0) >= 0.25:
        return True
    if reasons_reviewable:
        return True
    return text_reviewable


def _event_reasons_are_reviewable(reasons: list[str]) -> bool:
    review_words = (
        "adult",
        "bait",
        "blocked",
        "crypto",
        "domain",
        "invite",
        "link",
        "obfuscated",
        "phishing",
        "porn",
        "private",
        "reward",
        "scam",
        "sexual",
        "spam",
        "suspicious",
        "telegram",
        "zero-width",
    )
    return any(word in reason.casefold() for reason in reasons for word in review_words)


def _event_text_is_reviewable(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.search(
            r"\b(?:watch\s+now|see\s+more|tap\s+to\s+watch|link\s+expires|"
            r"onlyfans|xxx|nsfw|porn|nudes?|video\s+call|naked|pussy|cock|dick|fucked|swallowed|"
            r"riding|hot\s+instagram|instagram\s+girl|hidden\s+cam|private\s+tape|"
            r"fuck\s*mate|f\s*ck\s*mate|sex\s+partner|hookup\s+anyone|anyone\s+horny|"
            r"dm\s+me\b.{0,70}\b(?:i\s+have\s+it|link|file)|"
            r"pm\s+me\b.{0,70}\b(?:i\s+have\s+it|link|file)|"
            r"claim\s+reward|connect\s+wallet|verify\s+your\s+account)\b|"
            r"(?:t|telegram)\.me/[a-z0-9_]*bot(?:\?|/)?",
            text,
            flags=re.IGNORECASE,
        )
    )


def list_groups(session: Session) -> list[Group]:
    return list(session.scalars(select(Group).order_by(Group.created_at.desc())).all())


def get_group_by_id(session: Session, group_id: int) -> Group | None:
    return session.scalar(select(Group).where(Group.id == group_id))


def set_group_authorized_by_id(session: Session, group_id: int, authorized: bool) -> Group | None:
    group = get_group_by_id(session, group_id)
    if group is None:
        return None
    group.authorized = authorized
    session.flush()
    return group


def set_group_authorized(
    session: Session,
    *,
    telegram_chat_id: int,
    authorized: bool,
    settings: Settings,
    title: str | None = None,
) -> Group:
    group = get_or_create_group(
        session,
        telegram_chat_id=telegram_chat_id,
        title=title,
        chat_type="supergroup",
        settings=settings,
    )
    group.authorized = authorized
    session.flush()
    return group


def _support_title_key(value: str | None) -> str:
    if not value:
        return ""
    value = value.casefold()
    value = re.sub(r"\b(?:season|series|s)\s*(\d+)\b", r" season \1 ", value)
    value = re.sub(
        r"\b(?:episode|ep|e)\s*(\d+)(?:\s*(?:-|\u2013)\s*\d+)?\b",
        r" episode \1 ",
        value,
    )
    value = re.sub(
        r"\b(?:requesting|request|please|pls|plz|fix|link|links|broken|expired|"
        r"missing|banned|removed|movie|show|tv)\b",
        " ",
        value,
    )
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()[:255]


def _support_item_title(matched_title: str | None, title_query: str | None) -> str | None:
    return matched_title or title_query


def _support_key_has_part(key: str) -> bool:
    return bool(re.search(r"\b(?:season|episode)\s+\d+\b", key))


def _support_base_key(key: str) -> str:
    key = re.sub(r"\b(?:season|episode)\s+\d+\b", " ", key)
    return re.sub(r"\s+", " ", key).strip()


def _support_key_parts(key: str) -> dict[str, int]:
    parts: dict[str, int] = {}
    for label in ("season", "episode"):
        match = re.search(rf"\b{label}\s+(\d+)\b", key)
        if match:
            parts[label] = int(match.group(1))
    return parts


def _support_keys_compatible(incoming_key: str, candidate_key: str) -> bool:
    if incoming_key == candidate_key:
        return True
    if _support_base_key(incoming_key) != _support_base_key(candidate_key):
        return False
    incoming_parts = _support_key_parts(incoming_key)
    candidate_parts = _support_key_parts(candidate_key)
    if not incoming_parts or not candidate_parts:
        return True
    shared_labels = incoming_parts.keys() & candidate_parts.keys()
    if not shared_labels:
        return False
    for label in shared_labels:
        if incoming_parts[label] != candidate_parts[label]:
            return False
    return True


def find_support_request_merge_candidate(
    session: Session,
    *,
    group_id: int,
    title_query: str,
    status: str,
    category_hint: str | None,
    matched_show_id: int | None = None,
    matched_title: str | None = None,
) -> SupportRequest | None:
    query = select(SupportRequest).where(
        SupportRequest.group_id == group_id,
        SupportRequest.status == status,
    )
    if matched_show_id is not None:
        existing = session.scalar(query.where(SupportRequest.matched_show_id == matched_show_id))
        if existing:
            return existing

    incoming_key = _support_title_key(_support_item_title(matched_title, title_query))
    if not incoming_key:
        return None
    candidates = list(session.scalars(query.limit(50)).all())
    for candidate in candidates:
        if category_hint and candidate.category_hint and candidate.category_hint != category_hint:
            continue
        candidate_key = _support_title_key(
            _support_item_title(candidate.matched_title, candidate.title_query)
        )
        if _support_keys_compatible(incoming_key, candidate_key):
            return candidate
    return None


def upsert_support_request(
    session: Session,
    *,
    group_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    sender_user_id: int | None,
    title_query: str,
    category_hint: str | None,
    status: str,
    normalized_text: str,
    matched_show_id: int | None = None,
    matched_title: str | None = None,
    merge_request_id: int | None = None,
) -> SupportRequest:
    existing = (
        session.scalar(
            select(SupportRequest).where(
                SupportRequest.id == merge_request_id,
                SupportRequest.group_id == group_id,
                SupportRequest.status == status,
            )
        )
        if merge_request_id is not None
        else None
    )
    if existing is None:
        existing = find_support_request_merge_candidate(
            session,
            group_id=group_id,
            title_query=title_query,
            status=status,
            category_hint=category_hint,
            matched_show_id=matched_show_id,
            matched_title=matched_title,
        )
    if existing:
        existing.occurrence_count += 1
        existing.telegram_message_id = existing.telegram_message_id or telegram_message_id
        existing.sender_user_id = existing.sender_user_id or sender_user_id
        existing.normalized_text = normalized_text
        existing.matched_show_id = matched_show_id or existing.matched_show_id
        existing.matched_title = matched_title or existing.matched_title
        session.flush()
        return existing
    request = SupportRequest(
        group_id=group_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        sender_user_id=sender_user_id,
        title_query=title_query,
        category_hint=category_hint,
        status=status,
        normalized_text=normalized_text,
        matched_show_id=matched_show_id,
        matched_title=matched_title,
    )
    session.add(request)
    session.flush()
    return request


def find_support_issue_merge_candidate(
    session: Session,
    *,
    group_id: int,
    issue_type: str,
    title_query: str | None,
    category_hint: str | None,
    matched_show_id: int | None = None,
    matched_title: str | None = None,
) -> SupportIssue | None:
    query = select(SupportIssue).where(
        SupportIssue.group_id == group_id,
        SupportIssue.issue_type == issue_type,
        SupportIssue.status == "open",
    )
    if matched_show_id is not None:
        existing = session.scalar(query.where(SupportIssue.matched_show_id == matched_show_id))
        if existing:
            return existing

    incoming_key = _support_title_key(_support_item_title(matched_title, title_query))
    if not incoming_key:
        return None
    candidates = list(session.scalars(query.limit(50)).all())
    for candidate in candidates:
        if category_hint and candidate.category_hint and candidate.category_hint != category_hint:
            continue
        candidate_key = _support_title_key(
            _support_item_title(candidate.matched_title, candidate.title_query)
        )
        if _support_keys_compatible(incoming_key, candidate_key):
            return candidate
    return None


def upsert_support_issue(
    session: Session,
    *,
    group_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    sender_user_id: int | None,
    issue_type: str,
    title_query: str | None,
    category_hint: str | None,
    normalized_text: str,
    notes: str | None = None,
    matched_show_id: int | None = None,
    matched_title: str | None = None,
    merge_issue_id: int | None = None,
) -> SupportIssue:
    existing = (
        session.scalar(
            select(SupportIssue).where(
                SupportIssue.id == merge_issue_id,
                SupportIssue.group_id == group_id,
                SupportIssue.status == "open",
            )
        )
        if merge_issue_id is not None
        else None
    )
    if existing is None:
        existing = find_support_issue_merge_candidate(
            session,
            group_id=group_id,
            issue_type=issue_type,
            title_query=title_query,
            category_hint=category_hint,
            matched_show_id=matched_show_id,
            matched_title=matched_title,
        )
    if existing:
        existing.occurrence_count += 1
        existing.telegram_message_id = existing.telegram_message_id or telegram_message_id
        existing.sender_user_id = existing.sender_user_id or sender_user_id
        existing.normalized_text = normalized_text
        existing.notes = notes or existing.notes
        existing.matched_show_id = matched_show_id or existing.matched_show_id
        existing.matched_title = matched_title or existing.matched_title
        session.flush()
        return existing
    issue = SupportIssue(
        group_id=group_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        sender_user_id=sender_user_id,
        issue_type=issue_type,
        title_query=title_query,
        category_hint=category_hint,
        normalized_text=normalized_text,
        notes=notes,
        matched_show_id=matched_show_id,
        matched_title=matched_title,
    )
    session.add(issue)
    session.flush()
    return issue


def count_open_support_issues(session: Session, group_id: int | None = None) -> int:
    query = select(func.count(SupportIssue.id)).where(SupportIssue.status == "open")
    if group_id is not None:
        query = query.where(SupportIssue.group_id == group_id)
    return int(session.scalar(query) or 0)


def count_open_support_requests(session: Session, group_id: int | None = None) -> int:
    query = select(func.count(SupportRequest.id)).where(SupportRequest.status == "open")
    if group_id is not None:
        query = query.where(SupportRequest.group_id == group_id)
    return int(session.scalar(query) or 0)


def list_recent_support_issues(
    session: Session,
    group_id: int | None = None,
    *,
    limit: int = 10,
    status: str | None = "open",
) -> list[SupportIssue]:
    query = select(SupportIssue).order_by(SupportIssue.updated_at.desc()).limit(limit)
    if group_id is not None:
        query = query.where(SupportIssue.group_id == group_id)
    if status is not None:
        query = query.where(SupportIssue.status == status)
    return list(session.scalars(query).all())


def list_recent_support_requests(
    session: Session,
    group_id: int | None = None,
    *,
    limit: int = 10,
    status: str | None = "open",
) -> list[SupportRequest]:
    query = select(SupportRequest).order_by(SupportRequest.updated_at.desc()).limit(limit)
    if group_id is not None:
        query = query.where(SupportRequest.group_id == group_id)
    if status is not None:
        query = query.where(SupportRequest.status == status)
    return list(session.scalars(query).all())


def get_support_issue(session: Session, issue_id: int) -> SupportIssue | None:
    return session.scalar(select(SupportIssue).where(SupportIssue.id == issue_id))


def get_support_request(session: Session, request_id: int) -> SupportRequest | None:
    return session.scalar(select(SupportRequest).where(SupportRequest.id == request_id))


def set_support_issue_status(
    session: Session,
    issue_id: int,
    status: str,
    *,
    notes: str | None = None,
) -> SupportIssue | None:
    issue = get_support_issue(session, issue_id)
    if issue is None:
        return None
    issue.status = status
    issue.notes = notes or issue.notes
    session.flush()
    return issue


def set_support_request_status(
    session: Session,
    request_id: int,
    status: str,
) -> SupportRequest | None:
    request = get_support_request(session, request_id)
    if request is None:
        return None
    request.status = status
    session.flush()
    return request


def _catalog_key(value: str) -> str:
    value = re.sub(r"[^\w\s'&.-]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value.casefold()[:255]


def replace_tvweb_catalog(session: Session, items: list[Any]) -> int:
    session.execute(delete(TvwebCatalogItem))
    catalog_rows = [
        TvwebCatalogItem(
            tvweb_id=int(item.id),
            title=str(item.title)[:255],
            title_key=_catalog_key(str(item.title)),
            episode_title=(str(item.episode_title)[:255] if item.episode_title else None),
            category=str(item.category or "tv")[:32],
            slug=str(item.slug)[:512],
            year=item.year,
            rating=item.rating,
            download_link=item.download_link,
            source_updated_at=getattr(item, "source_updated_at", None),
        )
        for item in items
    ]
    session.add_all(catalog_rows)
    sync = get_or_create_tvweb_catalog_sync(session)
    sync.last_refresh_at = datetime.now(tz=UTC)
    sync.item_count = len(catalog_rows)
    sync.last_error = None
    session.flush()
    return len(catalog_rows)


def get_or_create_tvweb_catalog_sync(
    session: Session,
    label: str = "default",
) -> TvwebCatalogSync:
    sync = session.scalar(select(TvwebCatalogSync).where(TvwebCatalogSync.label == label))
    if sync is None:
        sync = TvwebCatalogSync(label=label, item_count=0)
        session.add(sync)
        session.flush()
    return sync


def get_tvweb_catalog_sync(
    session: Session,
    label: str = "default",
) -> TvwebCatalogSync | None:
    return session.scalar(select(TvwebCatalogSync).where(TvwebCatalogSync.label == label))


def record_tvweb_catalog_error(session: Session, error: str) -> None:
    sync = get_or_create_tvweb_catalog_sync(session)
    sync.last_error = error[:2000]
    session.flush()


def count_tvweb_catalog_items(session: Session) -> int:
    return int(session.scalar(select(func.count(TvwebCatalogItem.id))) or 0)


def save_tutorial_asset(
    session: Session,
    *,
    label: str,
    file_id: str,
    file_type: str,
    caption: str | None,
    source_chat_id: int | None,
    source_message_id: int | None,
    created_by_admin_id: int | None,
) -> TutorialAsset:
    asset = session.scalar(select(TutorialAsset).where(TutorialAsset.label == label))
    if asset is None:
        asset = TutorialAsset(label=label, file_id=file_id, file_type=file_type)
        session.add(asset)
    asset.file_id = file_id
    asset.file_type = file_type
    asset.caption = caption
    asset.source_chat_id = source_chat_id
    asset.source_message_id = source_message_id
    asset.created_by_admin_id = created_by_admin_id
    session.flush()
    return asset


def get_tutorial_asset(session: Session, label: str = "default") -> TutorialAsset | None:
    return session.scalar(select(TutorialAsset).where(TutorialAsset.label == label))


def record_bot_sent_message(
    session: Session,
    *,
    chat_id: int,
    message_id: int,
    purpose: str,
    delete_after: datetime | None,
) -> BotSentMessage:
    sent = BotSentMessage(
        chat_id=chat_id,
        message_id=message_id,
        purpose=purpose,
        delete_after=delete_after,
    )
    session.add(sent)
    session.flush()
    return sent


def list_bot_sent_messages(
    session: Session,
    *,
    chat_id: int,
    purposes: set[str] | frozenset[str] | tuple[str, ...],
) -> list[BotSentMessage]:
    return list(
        session.scalars(
            select(BotSentMessage).where(
                BotSentMessage.chat_id == chat_id,
                BotSentMessage.purpose.in_(purposes),
            )
        ).all()
    )


def due_bot_sent_messages(session: Session, now: datetime) -> list[BotSentMessage]:
    return list(
        session.scalars(
            select(BotSentMessage).where(
                BotSentMessage.delete_after.is_not(None),
                BotSentMessage.delete_after <= now,
            )
        ).all()
    )


def delete_bot_sent_message_record(session: Session, sent_id: int) -> None:
    session.execute(delete(BotSentMessage).where(BotSentMessage.id == sent_id))


def forget_group_data(session: Session, group_id: int) -> None:
    group = session.scalar(select(Group).where(Group.id == group_id))
    event_ids = select(ModerationEvent.id).where(ModerationEvent.group_id == group_id)
    session.execute(delete(PendingReview).where(PendingReview.moderation_event_id.in_(event_ids)))
    if group is not None:
        session.execute(
            delete(BotSentMessage).where(BotSentMessage.chat_id == group.telegram_chat_id)
        )
    for model in (
        SupportIssue,
        SupportRequest,
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
