from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.bot.support_actions import send_tutorial_if_available
from app.config import Settings
from app.db import repositories
from app.moderation.feature_extractor import SenderContext, extract_features
from app.moderation.normalizer import NormalizedMessage, normalize_telegram_message
from app.moderation.rules import RuleScore, compute_rule_score
from app.support.assistant import SupportIntent, build_support_reply, detect_support_intent
from app.support.ibox_search import search_tvweb_cache
from app.support.intent_ai import classify_support_intent_with_ai
from app.support.responder import render_support_reply

PRIVATE_MEDIA_FIELDS = (
    "animation",
    "audio",
    "document",
    "photo",
    "sticker",
    "video",
    "video_note",
    "voice",
)
ABUSE_RE = re.compile(
    r"\b(?:fuck\s+you|stupid\s+bot|idiot|moron|bitch|shut\s+up|useless\s+bot)\b",
    re.IGNORECASE,
)
INAPPROPRIATE_RE = re.compile(
    r"\b(?:send\s+nudes?|nudes?|onlyfans|xxx|porn|sex\s+video|explicit\s+video)\b",
    re.IGNORECASE,
)
MALICIOUS_CODE_RE = re.compile(
    r"(?:rm\s+-rf\s+/|curl\s+\S+\s*\|\s*(?:sh|bash)|wget\s+\S+\s*\|\s*(?:sh|bash)|"
    r"powershell\b.*-enc(?:odedcommand)?|subprocess\.(?:popen|run)\(|os\.system\(|"
    r"eval\s*\(\s*base64|document\.cookie|<script\b|drop\s+table\b)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class PrivateSafetyDecision:
    action: str
    score: float
    reasons: list[str]
    reply_text: str
    ai_label: str = "suspicious"
    count_as_violation: bool = True


@dataclass(frozen=True, slots=True)
class PrivateSafetyCheck:
    decision: PrivateSafetyDecision | None
    features: object
    rule_score: RuleScore


def private_user_help_text() -> str:
    return (
        "Hey. I can help with iBOX TV requests, search, broken or expired links, "
        "missing episodes, and download/play tutorial questions.\n\n"
        "Try: \"requesting Avatar\", \"Lioness link expired\", or \"how do I download?\" "
        "Keep it clean though; spam goes straight to the timeout corner."
    )


def private_message_has_media(message: object) -> bool:
    return any(bool(getattr(message, field, None)) for field in PRIVATE_MEDIA_FIELDS)


def classify_private_safety(
    *,
    normalized: NormalizedMessage,
    has_private_media: bool,
    previous_violation_score: float = 0.0,
) -> PrivateSafetyCheck:
    sender = SenderContext(previous_violation_score=previous_violation_score)
    features = extract_features(normalized, sender=sender)
    rule_score = compute_rule_score(features)
    score = rule_score.score
    reasons = list(rule_score.reasons)
    text = normalized.text

    abuse = bool(ABUSE_RE.search(text))
    inappropriate = bool(INAPPROPRIATE_RE.search(text))
    malicious_code = bool(MALICIOUS_CODE_RE.search(text))
    media_only = has_private_media and not text

    if abuse:
        score = max(score, 0.72)
        reasons.append("abusive private message")
    if inappropriate:
        score = max(score, 0.78)
        reasons.append("inappropriate private content")
    if malicious_code:
        score = max(score, 0.88)
        reasons.append("malicious code or exploit pattern")
    if media_only:
        score = max(score, 0.58)
        reasons.append("unsupported private media")
    if (
        features.high_risk_link
        or features.contains_adult_spam_cta
        or features.contains_suspicious_adult_story_lure
        or features.contains_crypto_scam
        or features.contains_fake_reward
        or features.contains_telegram_login_phishing_language
    ):
        score = max(score, 0.92)

    if previous_violation_score >= 0.12 and score >= 0.50:
        score = max(score, 0.72)
        reasons.append("previous private violations")

    reasons = list(dict.fromkeys(reasons))
    if score < 0.55:
        return PrivateSafetyCheck(decision=None, features=features, rule_score=rule_score)

    if media_only:
        decision = PrivateSafetyDecision(
            action="private_media_rejected",
            score=score,
            reasons=reasons,
            reply_text=(
                "I can't inspect random private media. Type the issue in words and I can help. "
                "Tiny tragedy, very survivable."
            ),
            ai_label="suspicious",
        )
    elif malicious_code:
        decision = PrivateSafetyDecision(
            action="private_malicious_code_ignored",
            score=score,
            reasons=reasons,
            reply_text=(
                "Nope. I handle iBOX support, not mystery code drops. Ask a normal support "
                "question and we are friends again."
            ),
            ai_label="spam",
        )
    elif score >= 0.90:
        decision = PrivateSafetyDecision(
            action="private_spam_ignored",
            score=score,
            reasons=reasons,
            reply_text=(
                "That looks like spam or unsafe content, so I am not engaging with it. "
                "Ask an iBOX support question if you actually need help."
            ),
            ai_label="spam",
        )
    else:
        decision = PrivateSafetyDecision(
            action="private_abuse_warned",
            score=score,
            reasons=reasons,
            reply_text=(
                "I can help with iBOX TV questions. Insults, explicit stuff, and sketchy "
                "payloads get ignored. Choose peace. Or at least choose a movie title."
            ),
            ai_label="suspicious",
        )
    return PrivateSafetyCheck(decision=decision, features=features, rule_score=rule_score)


async def handle_private_user_support(
    *,
    message: object,
    session: Session,
    settings: Settings,
) -> bool:
    if not settings.private_support_enabled:
        await message.answer("Private support is currently disabled.")
        return True

    normalized = normalize_telegram_message(message)
    user = getattr(message, "from_user", None)
    sender_user_id = getattr(user, "id", None)
    if user is not None:
        repositories.get_or_create_user(session, user)
    chat = getattr(message, "chat", None)
    group = repositories.get_or_create_group(
        session,
        telegram_chat_id=int(chat.id),
        title=_private_title(user),
        chat_type="private",
        settings=settings,
    )

    previous_score = repositories.get_violation_score(session, group.id, sender_user_id)
    safety = classify_private_safety(
        normalized=normalized,
        has_private_media=private_message_has_media(message),
        previous_violation_score=previous_score,
    )
    if safety.decision is not None:
        await _handle_private_safety_decision(
            message=message,
            session=session,
            settings=settings,
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            sender_user_id=sender_user_id,
            normalized=normalized,
            safety=safety,
        )
        return True

    if not normalized.text:
        await message.answer(
            "Type the question in words and I can help. I am clever, but not "
            "telepathic-through-attachments clever."
        )
        return True

    intent = detect_support_intent(normalized.text, allow_bare_title=False)
    if intent is None:
        intent = await classify_support_intent_with_ai(text=normalized.text, settings=settings)
    if intent is None:
        intent = detect_support_intent(normalized.text, allow_bare_title=True)
    if intent is None:
        await message.answer(
            private_user_help_text(),
            disable_web_page_preview=True,
        )
        return True

    matches = []
    if intent.title_query:
        matches = search_tvweb_cache(
            session=session,
            settings=settings,
            query=intent.title_query,
            category=intent.category_hint,
        )
    reply_intent = _private_reply_intent(intent, matches)
    reply = build_support_reply(intent=reply_intent, matches=matches, settings=settings)
    if reply is None:
        await message.answer(private_user_help_text(), disable_web_page_preview=True)
        return True

    _record_private_support_intent(
        session=session,
        group_id=group.id,
        telegram_chat_id=group.telegram_chat_id,
        telegram_message_id=int(getattr(message, "message_id", 0)),
        sender_user_id=sender_user_id,
        intent=reply_intent,
        normalized=normalized,
        matches=matches,
        settings=settings,
    )
    reply_text = await render_support_reply(
        factual_reply=reply,
        intent=reply_intent,
        matches=matches,
        settings=settings,
        user_text=normalized.text,
    )
    await message.answer(reply_text, disable_web_page_preview=True)
    if reply.should_send_tutorial:
        await send_tutorial_if_available(
            bot=getattr(message, "bot", None),
            session=session,
            chat_id=group.telegram_chat_id,
            settings=settings,
            cleanup=False,
        )
    return True


async def _handle_private_safety_decision(
    *,
    message: object,
    session: Session,
    settings: Settings,
    group_id: int,
    telegram_chat_id: int,
    sender_user_id: int | None,
    normalized: NormalizedMessage,
    safety: PrivateSafetyCheck,
) -> None:
    decision = safety.decision
    if decision is None:
        return
    repositories.record_moderation_event(
        session,
        group_id=group_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=int(getattr(message, "message_id", 0)),
        sender_user_id=sender_user_id,
        normalized_text=normalized.text,
        text_hash=normalized.text_hash,
        domains=normalized.domains,
        ai_label=decision.ai_label,
        ai_confidence=decision.score,
        rule_score=safety.rule_score.score,
        final_score=decision.score,
        action_taken=decision.action,
        action_status="logged",
        reasons=decision.reasons,
        provider_name="private_rules",
        model_name="rules",
        prompt_version="private-safety-v1",
    )
    violation_count = 0
    if decision.count_as_violation and sender_user_id is not None:
        violation = repositories.record_violation(
            session,
            group_id=group_id,
            telegram_user_id=sender_user_id,
            action=decision.action,
            score=decision.score,
        )
        violation_count = violation.violation_count

    if violation_count > settings.private_abuse_silence_after:
        return
    if violation_count == settings.private_abuse_silence_after:
        await message.answer(
            "Last warning from the tiny support desk. More spam or abuse and I stop replying here.",
            parse_mode=None,
        )
        return
    await message.answer(decision.reply_text, parse_mode=None)


def _private_reply_intent(intent: SupportIntent, matches: list[object]) -> SupportIntent:
    if intent.kind == "bare_title" and not matches:
        return SupportIntent(
            kind="request",
            title_query=intent.title_query,
            category_hint=intent.category_hint,
        )
    return intent


def _record_private_support_intent(
    *,
    session: Session,
    group_id: int,
    telegram_chat_id: int,
    telegram_message_id: int,
    sender_user_id: int | None,
    intent: SupportIntent,
    normalized: NormalizedMessage,
    matches: list[object],
    settings: Settings,
) -> None:
    if intent.kind in {"request", "bare_title"} and intent.title_query:
        repositories.upsert_support_request(
            session,
            group_id=group_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            sender_user_id=sender_user_id,
            title_query=intent.title_query,
            category_hint=intent.category_hint,
            status="found" if matches else "open" if settings.tvweb_database_url else "suggested_search",
            normalized_text=normalized.text,
            matched_show_id=getattr(matches[0], "id", None) if matches else None,
            matched_title=getattr(matches[0], "display_title", None) if matches else None,
        )
    elif intent.kind == "issue":
        repositories.upsert_support_issue(
            session,
            group_id=group_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            sender_user_id=sender_user_id,
            issue_type=intent.issue_type or "general",
            title_query=intent.title_query,
            category_hint=intent.category_hint,
            normalized_text=normalized.text,
            matched_show_id=getattr(matches[0], "id", None) if matches else None,
            matched_title=getattr(matches[0], "display_title", None) if matches else None,
        )


def _private_title(user: object | None) -> str:
    if user is None:
        return "Private support user"
    username = getattr(user, "username", None)
    first = getattr(user, "first_name", None)
    last = getattr(user, "last_name", None)
    name = " ".join(part for part in (first, last) if part).strip()
    if username and name:
        return f"{name} (@{username})"
    if name:
        return name
    if username:
        return f"@{username}"
    return "Private support user"
