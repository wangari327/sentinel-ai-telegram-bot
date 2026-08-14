from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.bot.support_actions import (
    schedule_cleanup,
    send_ephemeral_message,
    send_tutorial_if_available,
)
from app.bot.telegram_actions import notify_admin_about_event
from app.config import Settings
from app.db import repositories
from app.db.models import Group
from app.moderation.actions import ActionResult, execute_telegram_decision
from app.moderation.ai_classifier import (
    ClassificationRequest,
    ClassificationResult,
    RulesOnlyProvider,
    get_ai_provider,
)
from app.moderation.feature_extractor import SenderContext, extract_features
from app.moderation.normalizer import NormalizedMessage, normalize_telegram_message
from app.moderation.rules import compute_rule_score
from app.moderation.scoring import Decision, combine_scores, decide_action
from app.moderation.similarity import retrieve_examples
from app.support.assistant import build_support_reply, detect_support_intent
from app.support.ibox_search import search_tvweb_cache
from app.support.responder import render_support_reply


@dataclass(frozen=True, slots=True)
class PipelineResult:
    status: str
    decision: Decision | None = None
    ai_result: ClassificationResult | None = None
    action_result: ActionResult | None = None
    final_score: float = 0.0
    reasons: list[str] | None = None
    support_replied: bool = False


def should_skip(
    *,
    normalized: NormalizedMessage,
    sender: SenderContext,
    scan_admins: bool,
) -> bool:
    if not normalized.text:
        return True
    if sender.is_admin and not scan_admins:
        return True
    if sender.is_trusted:
        extreme = any(
            
                "t.me/" in link.lower() and ("start=" in link.lower() or "joinchat/" in link.lower())
                for link in normalized.telegram_links
            
        )
        return not extreme
    return False


def should_call_ai(*, features: object, group_settings: object) -> bool:
    if getattr(group_settings, "ai_scan_all_messages", False):
        return True
    if getattr(group_settings, "ai_scan_links_only", True) and not getattr(features, "contains_url", False):
        return False
    return getattr(features, "risk_signal_count", 0) > 0


async def maybe_handle_support_message(
    *,
    message: object,
    bot: object,
    session: Session,
    settings: Settings,
    group: Group,
    normalized: NormalizedMessage,
    sender_user_id: int | None,
) -> bool:
    if not settings.support_enabled:
        return False
    intent = detect_support_intent(
        normalized.text,
        allow_bare_title=settings.tvweb_cache_enabled,
    )
    if intent is None:
        return False
    matches = []
    if intent.title_query:
        matches = search_tvweb_cache(
            session=session,
            settings=settings,
            query=intent.title_query,
            category=intent.category_hint,
        )
    reply = build_support_reply(intent=intent, matches=matches, settings=settings)
    if reply is None:
        return False
    reply_text = await render_support_reply(
        factual_reply=reply,
        intent=intent,
        matches=matches,
        settings=settings,
        user_text=normalized.text,
    )

    if intent.kind == "request" and intent.title_query:
        repositories.upsert_support_request(
            session,
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            telegram_message_id=int(getattr(message, "message_id", 0)),
            sender_user_id=sender_user_id,
            title_query=intent.title_query,
            category_hint=intent.category_hint,
            status="found" if matches else "open" if settings.tvweb_database_url else "suggested_search",
            normalized_text=normalized.text,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
        )
    if intent.kind == "issue":
        repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            telegram_message_id=int(getattr(message, "message_id", 0)),
            sender_user_id=sender_user_id,
            issue_type=intent.issue_type or "general",
            title_query=intent.title_query,
            category_hint=intent.category_hint,
            normalized_text=normalized.text,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
        )

    await send_ephemeral_message(
        bot=bot,
        session=session,
        chat_id=group.telegram_chat_id,
        text=reply_text,
        settings=settings,
        reply_to_message_id=int(getattr(message, "message_id", 0)),
    )
    if reply.should_send_tutorial:
        await send_tutorial_if_available(
            bot=bot,
            session=session,
            chat_id=group.telegram_chat_id,
            settings=settings,
            reply_to_message_id=int(getattr(message, "message_id", 0)),
        )
    schedule_cleanup(bot=bot, delay_seconds=settings.support_reply_cleanup_seconds)
    return True


def _message_sender_context(
    *,
    message: object,
    is_admin: bool,
    is_trusted: bool,
    previous_violation_score: float,
) -> SenderContext:
    user = getattr(message, "from_user", None)
    full_name = " ".join(
        part
        for part in (
            getattr(user, "first_name", None),
            getattr(user, "last_name", None),
        )
        if part
    )
    return SenderContext(
        user_id=getattr(user, "id", None),
        username=getattr(user, "username", None),
        display_name=full_name or None,
        is_admin=is_admin,
        is_trusted=is_trusted,
        previous_violation_score=previous_violation_score,
    )


async def process_group_message(
    *,
    message: object,
    bot: object,
    session: Session,
    settings: Settings,
    permissions: object,
    sender_is_admin: bool,
) -> PipelineResult:
    chat = getattr(message, "chat", None)
    chat_id = int(chat.id)
    group = repositories.get_or_create_group(
        session,
        telegram_chat_id=chat_id,
        title=getattr(chat, "title", None),
        chat_type=getattr(chat, "type", "supergroup"),
        settings=settings,
    )
    group_settings = repositories.get_or_create_group_settings(session, group, settings)
    if not repositories.chat_is_authorized(group, settings):
        return PipelineResult(status="skipped_unauthorized_chat")

    user = getattr(message, "from_user", None)
    sender_user_id = getattr(user, "id", None)
    normalized = normalize_telegram_message(message)
    is_trusted = repositories.is_trusted_user(session, group.id, sender_user_id)
    previous_violation_score = repositories.get_violation_score(session, group.id, sender_user_id)
    sender = _message_sender_context(
        message=message,
        is_admin=sender_is_admin,
        is_trusted=is_trusted,
        previous_violation_score=previous_violation_score,
    )
    if should_skip(
        normalized=normalized,
        sender=sender,
        scan_admins=bool(group_settings.scan_admins),
    ):
        return PipelineResult(status="skipped")

    domain_statuses = repositories.get_domain_statuses(session, group.id, normalized.domains)
    features = extract_features(
        normalized,
        sender=sender,
        domain_statuses=domain_statuses,
    )
    rule_score = compute_rule_score(features)
    spam_examples, good_examples, spam_similarity, not_spam_similarity = retrieve_examples(
        session,
        group_id=group.id,
        normalized_text=normalized.text,
        global_enabled=bool(group_settings.global_training_enabled),
    )

    request = ClassificationRequest(
        normalized_text=normalized.text,
        raw_excerpt=normalized.raw_excerpt,
        urls=normalized.urls,
        domains=normalized.domains,
        telegram_links=normalized.telegram_links,
        rule_features=features.to_dict(),
        rule_score=rule_score.score,
        sender_context=asdict(sender),
        group_context={
            "group_id": group.id,
            "telegram_chat_id": group.telegram_chat_id,
            "mode": group_settings.mode,
            "setup_completed": group.setup_completed,
        },
        recent_user_behavior={"previous_violation_score": previous_violation_score},
        relevant_spam_examples=[example.raw_excerpt for example in spam_examples[:4]],
        relevant_not_spam_examples=[example.raw_excerpt for example in good_examples[:4]],
    )
    if should_call_ai(features=features, group_settings=group_settings):
        ai_result = await get_ai_provider(settings).classify(request)
    else:
        ai_result = await RulesOnlyProvider().classify(request)

    score = combine_scores(
        rule_score=rule_score,
        ai_result=ai_result,
        features=features,
        spam_similarity=spam_similarity,
        not_spam_similarity=not_spam_similarity,
        sender_violation_score=previous_violation_score,
    )
    decision = decide_action(
        score=score,
        ai_result=ai_result,
        features=features,
        settings=group_settings,
        setup_completed=bool(group.setup_completed),
        demo_mode=settings.demo_mode,
    )
    event = repositories.save_moderation_event(
        session,
        group_id=group.id,
        telegram_chat_id=group.telegram_chat_id,
        telegram_message_id=int(getattr(message, "message_id", 0)),
        sender_user_id=sender_user_id,
        normalized_text=normalized.text,
        text_hash=normalized.text_hash,
        domains=normalized.domains,
        ai_label=ai_result.label,
        ai_confidence=ai_result.confidence,
        rule_score=rule_score.score,
        final_score=score.final_score,
        action_taken=decision.action,
        action_status="planned",
        reasons=score.reasons,
        provider_name=ai_result.provider_name,
        model_name=ai_result.model_name,
        prompt_version=ai_result.prompt_version,
        provider_error=ai_result.error,
    )

    action_result = await execute_telegram_decision(
        bot=bot,
        chat_id=chat_id,
        message_id=int(getattr(message, "message_id", 0)),
        sender_user_id=sender_user_id,
        decision=decision,
        can_delete=bool(getattr(permissions, "can_delete_messages", False)),
        can_ban=bool(getattr(permissions, "can_restrict_members", False)),
    )
    event.action_status = action_result.error or "ok"
    if (decision.delete or decision.ban) and sender_user_id is not None:
        repositories.record_violation(
            session,
            group_id=group.id,
            telegram_user_id=sender_user_id,
            action=decision.action,
            score=score.final_score,
        )

    if decision.notify_admin or decision.pending_review:
        await notify_admin_about_event(
            bot=bot,
            session=session,
            admin_user_id=group_settings.notify_admin_user_id or settings.default_notify_admin_id,
            event_id=event.id,
            group_title=group.title,
            display_name=sender.display_name,
            username=sender.username,
            user_id=sender.user_id,
            action=decision.action,
            ai_label=ai_result.label,
            confidence=ai_result.confidence,
            reasons=score.reasons,
            excerpt=normalized.raw_excerpt,
            domains=normalized.domains,
        )

    support_replied = False
    if not decision.delete and not decision.ban and ai_result.label == "not_spam":
        support_replied = await maybe_handle_support_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            group=group,
            normalized=normalized,
            sender_user_id=sender_user_id,
        )

    return PipelineResult(
        status="processed",
        decision=decision,
        ai_result=ai_result,
        action_result=action_result,
        final_score=score.final_score,
        reasons=score.reasons,
        support_replied=support_replied,
    )


def group_is_authorized(group: Group | None, settings: Settings) -> bool:
    return repositories.chat_is_authorized(group, settings)
