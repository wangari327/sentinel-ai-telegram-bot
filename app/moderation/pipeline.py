from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, replace
from html import escape
from time import monotonic

from sqlalchemy.orm import Session

from app.bot.keyboards import support_reply_keyboard
from app.bot.support_actions import (
    schedule_cleanup,
    send_ephemeral_message,
    send_tutorial_if_available,
)
from app.bot.telegram_actions import notify_admin_about_event
from app.config import Settings
from app.db import repositories
from app.db.models import Group
from app.logging import get_logger
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
from app.support.assistant import (
    SupportIntent,
    SupportReply,
    availability_blocks_logging,
    availability_confirms_requested_part_ready,
    build_availability_reply,
    build_catalog_ahead_of_release_reply,
    build_catalog_base_found_reply,
    build_log_vetting_reply,
    build_support_reply,
    catalog_requested_season_is_ahead,
    detect_support_intent,
    extract_support_context_title,
    filter_matches_for_requested_part,
    title_query_with_requested_part,
)
from app.support.ibox_search import (
    IboxItem,
    normalize_title_query,
    search_tvweb,
    search_tvweb_cache,
)
from app.support.intent_ai import (
    choose_support_merge_candidate_with_ai,
    classify_support_intent_with_ai,
    vet_support_log_with_ai,
)
from app.support.responder import render_support_reply
from app.support.tmdb import TmdbAvailability, resolve_tmdb_availability

logger = get_logger(__name__)
_RECENT_CONTEXT_TTL_SECONDS = 900
_RECENT_CONTEXT_LIMIT = 30
_RECENT_GROUP_TEXTS: dict[int, deque[tuple[float, str]]] = defaultdict(
    lambda: deque(maxlen=_RECENT_CONTEXT_LIMIT)
)


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
            ("t.me/" in link.lower() or "telegram.me/" in link.lower())
            and (
                "start=" in link.lower()
                or "startapp=" in link.lower()
                or "joinchat/" in link.lower()
            )
            for link in normalized.telegram_links
        )
        return not extreme
    return False


def auto_complete_authorized_group_setup(
    *,
    group: Group,
    settings: Settings,
    permissions: object,
) -> bool:
    if group.setup_completed:
        return False
    if not repositories.chat_is_authorized(group, settings):
        return False
    if not bool(getattr(permissions, "is_admin", False)):
        return False
    if not bool(getattr(permissions, "can_delete_messages", False)):
        return False
    group.setup_completed = True
    return True


def should_call_ai(*, features: object, group_settings: object) -> bool:
    if getattr(group_settings, "ai_scan_all_messages", False):
        return True
    risky_text_without_url = any(
        getattr(features, field, False)
        for field in (
            "contains_porn_bait",
            "contains_sexual_solicitation",
            "contains_adult_spam_cta",
            "contains_suspicious_adult_story_lure",
            "contains_private_solicitation",
            "contains_crypto_scam",
            "contains_fake_reward",
            "contains_telegram_login_phishing_language",
        )
    )
    if getattr(group_settings, "ai_scan_links_only", True) and not getattr(
        features, "contains_url", False
    ):
        return risky_text_without_url
    return getattr(features, "risk_signal_count", 0) > 0


def is_linked_channel_announcement(message: object) -> bool:
    if bool(getattr(message, "is_automatic_forward", False)):
        return True
    sender_chat = getattr(message, "sender_chat", None)
    return bool(
        sender_chat is not None
        and getattr(sender_chat, "type", None) == "channel"
        and getattr(message, "from_user", None) is None
    )


async def maybe_handle_support_message(
    *,
    message: object,
    bot: object,
    session: Session,
    settings: Settings,
    group: Group,
    normalized: NormalizedMessage,
    sender_user_id: int | None,
    recent_context_texts: list[str] | None = None,
) -> bool:
    if not settings.support_enabled:
        return False
    context_title = _message_reply_context_title(message)
    intent = detect_support_intent(
        normalized.text,
        allow_bare_title=False,
        context_title=context_title,
    )
    if intent is None:
        intent = detect_support_intent(
            normalized.text,
            allow_bare_title=settings.tvweb_cache_enabled,
            context_title=context_title,
        )
    if intent is None:
        intent = await classify_support_intent_with_ai(
            text=normalized.text,
            settings=settings,
        )
    if intent is None:
        return False
    matches = []
    if intent.title_query and intent.kind != "howto":
        matches = await _search_ibox_catalog(
            session=session,
            settings=settings,
            intent=intent,
        )

    availability: TmdbAvailability | None = None
    needs_availability = intent.kind == "release" or (
        intent.kind in {"request", "issue"} and not matches
    )
    if needs_availability and intent.title_query:
        availability = await resolve_tmdb_availability(
            settings=settings,
            title_query=intent.title_query,
            category_hint=intent.category_hint,
            season_number=intent.season_number,
            episode_number=intent.episode_number,
        )
        if availability_blocks_logging(intent, availability):
            reply = build_availability_reply(
                intent=intent,
                matches=matches,
                settings=settings,
                availability=availability,
            )
            if reply is not None:
                await _send_support_reply(
                    message=message,
                    bot=bot,
                    session=session,
                    settings=settings,
                    group=group,
                    normalized=normalized,
                    intent=intent,
                    matches=matches,
                    reply=reply,
                )
                return True
        matches = await _resolve_catalog_alias_matches(
            session=session,
            settings=settings,
            intent=intent,
            matches=matches,
            availability=availability,
        )
    if not matches and intent.title_query:
        matches = await _search_recent_context_catalog_matches(
            session=session,
            settings=settings,
            intent=intent,
            recent_context_texts=recent_context_texts or [],
        )

    catalog_matches_without_part: list[IboxItem] = []
    if (
        not matches
        and intent.kind in {"request", "issue"}
        and (intent.season_number is not None or intent.episode_number is not None)
    ):
        catalog_matches_without_part = await _search_catalog_without_requested_part(
            session=session,
            settings=settings,
            intent=intent,
        )
        requested_season_is_ahead = catalog_requested_season_is_ahead(
            intent=intent,
            catalog_matches=catalog_matches_without_part,
        )
        requested_part_is_ready = availability_confirms_requested_part_ready(intent, availability)
        if (
            not requested_part_is_ready
            and requested_season_is_ahead
        ):
            reply = build_catalog_ahead_of_release_reply(
                intent=intent,
                catalog_matches=catalog_matches_without_part,
                settings=settings,
                availability=availability,
            )
            await _send_support_reply(
                message=message,
                bot=bot,
                session=session,
                settings=settings,
                group=group,
                normalized=normalized,
                intent=intent,
                matches=catalog_matches_without_part,
                reply=reply,
            )
            return True
        if catalog_matches_without_part and intent.kind == "request" and not (
            requested_part_is_ready and requested_season_is_ahead
        ):
            reply = build_catalog_base_found_reply(
                intent=intent,
                catalog_matches=catalog_matches_without_part,
                settings=settings,
            )
            await _send_support_reply(
                message=message,
                bot=bot,
                session=session,
                settings=settings,
                group=group,
                normalized=normalized,
                intent=intent,
                matches=catalog_matches_without_part,
                reply=reply,
            )
            return True

    occurrence_count: int | None = None
    if intent.kind in {"request", "issue"} and intent.title_query and not matches:
        vet_result = await vet_support_log_with_ai(
            kind=intent.kind,
            text=normalized.text,
            intent=intent,
            availability_title=availability.title if availability else None,
            availability_state=availability.state() if availability else None,
            settings=settings,
        )
        if vet_result is not None:
            if vet_result.action == "retry_search" and vet_result.corrected_title_query:
                retry_matches = await _search_ibox_catalog_variants(
                    session=session,
                    settings=settings,
                    intent=intent,
                    queries=_title_query_variants(vet_result.corrected_title_query),
                )
                if retry_matches:
                    matches = retry_matches
                else:
                    reply = build_log_vetting_reply(
                        intent=intent,
                        settings=settings,
                        suggested_title=vet_result.corrected_title_query,
                    )
                    await _send_support_reply(
                        message=message,
                        bot=bot,
                        session=session,
                        settings=settings,
                        group=group,
                        normalized=normalized,
                        intent=intent,
                        matches=matches,
                        reply=reply,
                    )
                    return True
            elif vet_result.action == "clarify":
                reply = build_log_vetting_reply(
                    intent=intent,
                    settings=settings,
                    suggested_title=vet_result.corrected_title_query,
                )
                await _send_support_reply(
                    message=message,
                    bot=bot,
                    session=session,
                    settings=settings,
                    group=group,
                    normalized=normalized,
                    intent=intent,
                    matches=matches,
                    reply=reply,
                )
                return True
            elif vet_result.action == "skip":
                return False

    if intent.kind == "request" and intent.title_query:
        record_title_query = title_query_with_requested_part(intent) or intent.title_query
        status = (
            "found" if matches else "open" if settings.tvweb_database_url else "suggested_search"
        )
        merge_request_id = await _choose_request_merge_id(
            session=session,
            settings=settings,
            group_id=group.id,
            intent=intent,
            normalized=normalized,
            status=status,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
        )
        request = repositories.upsert_support_request(
            session,
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            telegram_message_id=int(getattr(message, "message_id", 0)),
            sender_user_id=sender_user_id,
            title_query=record_title_query,
            category_hint=intent.category_hint,
            status=status,
            normalized_text=normalized.text,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
            merge_request_id=merge_request_id,
        )
        occurrence_count = request.occurrence_count
    if intent.kind == "issue":
        record_title_query = title_query_with_requested_part(intent)
        issue_type = intent.issue_type or "general"
        merge_issue_id = await _choose_issue_merge_id(
            session=session,
            settings=settings,
            group_id=group.id,
            intent=intent,
            normalized=normalized,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
        )
        issue = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=group.telegram_chat_id,
            telegram_message_id=int(getattr(message, "message_id", 0)),
            sender_user_id=sender_user_id,
            issue_type=issue_type,
            title_query=record_title_query,
            category_hint=intent.category_hint,
            normalized_text=normalized.text,
            matched_show_id=matches[0].id if matches else None,
            matched_title=matches[0].display_title if matches else None,
            merge_issue_id=merge_issue_id,
        )
        occurrence_count = issue.occurrence_count

    reply = build_support_reply(
        intent=intent,
        matches=matches,
        settings=settings,
        occurrence_count=occurrence_count,
        availability=availability,
    )
    if reply is None:
        return False
    await _send_support_reply(
        message=message,
        bot=bot,
        session=session,
        settings=settings,
        group=group,
        normalized=normalized,
        intent=intent,
        matches=matches,
        reply=reply,
    )
    return True


async def _search_catalog_without_requested_part(
    *,
    session: Session,
    settings: Settings,
    intent: SupportIntent,
) -> list[IboxItem]:
    if not intent.title_query:
        return []
    stripped = replace(
        intent,
        season_number=None,
        season_end_number=None,
        episode_number=None,
        episode_end_number=None,
    )
    return await _search_ibox_catalog(session=session, settings=settings, intent=stripped)


async def _search_ibox_catalog(
    *,
    session: Session,
    settings: Settings,
    intent: SupportIntent,
) -> list[IboxItem]:
    if not intent.title_query:
        return []
    matches = search_tvweb_cache(
        session=session,
        settings=settings,
        query=intent.title_query,
        category=intent.category_hint,
    )
    filtered = filter_matches_for_requested_part(matches, intent)
    if filtered:
        return filtered

    if settings.tvweb_database_url:
        direct = await _search_ibox_database(settings=settings, intent=intent)
        if direct:
            return direct

    return []


async def _resolve_catalog_alias_matches(
    *,
    session: Session,
    settings: Settings,
    intent: SupportIntent,
    matches: list[IboxItem],
    availability: TmdbAvailability | None,
) -> list[IboxItem]:
    if matches or availability is None or not availability.found or not availability.title:
        return matches
    queries = _title_query_variants(availability.title)
    return await _search_ibox_catalog_variants(
        session=session,
        settings=settings,
        intent=intent,
        queries=queries,
    )


async def _search_ibox_catalog_variants(
    *,
    session: Session,
    settings: Settings,
    intent: SupportIntent,
    queries: list[str],
) -> list[IboxItem]:
    original = normalize_title_query(intent.title_query or "").casefold()
    seen: set[str] = {original} if original else set()
    for query in queries:
        key = normalize_title_query(query).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        matches = await _search_ibox_catalog(
            session=session,
            settings=settings,
            intent=replace(intent, title_query=query),
        )
        if matches:
            return matches
    return []


async def _search_recent_context_catalog_matches(
    *,
    session: Session,
    settings: Settings,
    intent: SupportIntent,
    recent_context_texts: list[str],
) -> list[IboxItem]:
    if not intent.title_query or not recent_context_texts:
        return []
    queries: list[str] = []
    for text in reversed(recent_context_texts[-10:]):
        queries.extend(_contextual_title_queries(intent=intent, context_text=text))
    return await _search_ibox_catalog_variants(
        session=session,
        settings=settings,
        intent=intent,
        queries=queries,
    )


def _contextual_title_queries(*, intent: SupportIntent, context_text: str) -> list[str]:
    if not intent.title_query or not context_text:
        return []
    query_words = [
        word
        for word in normalize_title_query(intent.title_query).casefold().split()
        if len(word) >= 3
    ]
    if not query_words:
        return []
    context_key = normalize_title_query(context_text).casefold()
    if not all(word in context_key for word in query_words):
        return []

    candidates: list[str] = []
    if intent.season_number is not None:
        season = str(intent.season_number).lstrip("0") or "0"
        patterns = (
            rf"(?i)([A-Za-z0-9][\w\s'&:.-]{{2,110}}?)\s+s0*{season}(?:\s*e0*\d{{1,4}})?\b",
            rf"(?i)([A-Za-z0-9][\w\s'&:.-]{{2,110}}?)\s+season\s*0*{season}\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, context_text):
                candidates.append(match.group(1))
    candidates.append(context_text)

    queries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = _clean_context_title_candidate(candidate)
        if not clean:
            continue
        for variant in _title_query_variants(clean):
            key = normalize_title_query(variant).casefold()
            if key and key not in seen:
                seen.add(key)
                queries.append(variant)
    return queries


def _clean_context_title_candidate(value: str) -> str | None:
    value = re.sub(r"https?://\S+|(?:t|telegram)\.me/\S+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mb|gb)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\b(?:480p|720p|1080p|2160p|4k|8k|10bit|x264|x265|hevc|h\.?264|h\.?265|"
        r"webrip|web-dl|bluray|hdrip|dual\s+audio|complete|download|click\s+here)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\bs0*\d{1,3}\s*e0*\d{1,4}\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bs0*\d{1,3}\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\b(?:season|series)\s*0*\d{1,3}(?:\s*(?:-|to)\s*0*\d{1,3})?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = normalize_title_query(value)
    value = re.sub(
        r"^(?:file|folder|page|no more pages available)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return value if len(value) >= 2 else None


def _title_query_variants(value: str | None) -> list[str]:
    if not value:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def add(candidate: str | None) -> None:
        if not candidate:
            return
        clean = normalize_title_query(candidate)
        key = clean.casefold()
        if len(clean) >= 2 and key not in seen:
            seen.add(key)
            variants.append(clean)

    add(value)
    for separator in (":", " - ", "|", "/"):
        if separator in value:
            parts = [part.strip() for part in value.split(separator) if part.strip()]
            for part in parts:
                add(part)
            if len(parts) >= 2:
                add(parts[-1])

    clean = normalize_title_query(value)
    words = [
        word
        for word in clean.split()
        if word.casefold()
        not in {
            "special",
            "ops",
            "operation",
            "operations",
            "the",
            "a",
            "an",
            "season",
            "series",
        }
    ]
    for size in range(min(3, len(words)), 0, -1):
        tail = " ".join(words[-size:])
        if len(tail) >= 4:
            add(tail)
    return variants


async def _search_ibox_database(
    *,
    settings: Settings,
    intent: SupportIntent,
) -> list[IboxItem]:
    if not intent.title_query:
        return []
    categories = [intent.category_hint]
    if intent.category_hint is not None:
        categories.append(None)
    has_requested_part = intent.season_number is not None or intent.episode_number is not None
    first_unfiltered: list[IboxItem] = []
    for category in categories:
        try:
            matches = await asyncio.to_thread(
                search_tvweb,
                settings=settings,
                query=intent.title_query,
                category=category,
                limit=12 if has_requested_part else 3,
            )
        except Exception:
            logger.exception(
                "Direct TVWEB_DATABASE_URL lookup failed query=%r category=%r",
                intent.title_query,
                category,
            )
            return []
        filtered = filter_matches_for_requested_part(matches, intent)
        if filtered:
            return filtered[:3]
        if matches:
            first_unfiltered = first_unfiltered or matches
    return [] if has_requested_part else first_unfiltered[:3]


async def _send_support_reply(
    *,
    message: object,
    bot: object,
    session: Session,
    settings: Settings,
    group: Group,
    normalized: NormalizedMessage,
    intent: SupportIntent,
    matches: list[IboxItem],
    reply: SupportReply,
) -> None:
    reply_text = await render_support_reply(
        factual_reply=reply,
        intent=intent,
        matches=matches,
        settings=settings,
        user_text=normalized.text,
    )
    await send_ephemeral_message(
        bot=bot,
        session=session,
        chat_id=group.telegram_chat_id,
        text=reply_text,
        settings=settings,
        reply_to_message_id=int(getattr(message, "message_id", 0)),
        reply_markup=support_reply_keyboard(reply.buttons),
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


def _message_reply_context_title(message: object) -> str | None:
    reply = getattr(message, "reply_to_message", None)
    if reply is None:
        return None
    raw_reply = "\n".join(
        part
        for part in (
            getattr(reply, "text", None),
            getattr(reply, "caption", None),
        )
        if part
    )
    if raw_reply:
        title = extract_support_context_title(raw_reply)
        if title:
            return title
    normalized_reply = normalize_telegram_message(reply)
    if not normalized_reply.text:
        return None
    return extract_support_context_title(normalized_reply.text)


async def _choose_issue_merge_id(
    *,
    session: Session,
    settings: Settings,
    group_id: int,
    intent: SupportIntent,
    normalized: NormalizedMessage,
    matched_show_id: int | None,
    matched_title: str | None,
) -> int | None:
    issue_type = intent.issue_type or "general"
    deterministic = repositories.find_support_issue_merge_candidate(
        session,
        group_id=group_id,
        issue_type=issue_type,
        title_query=title_query_with_requested_part(intent),
        category_hint=intent.category_hint,
        matched_show_id=matched_show_id,
        matched_title=matched_title,
    )
    if deterministic:
        return deterministic.id
    candidates = repositories.list_recent_support_issues(
        session,
        group_id=group_id,
        limit=12,
        status="open",
    )
    return await choose_support_merge_candidate_with_ai(
        kind="issue",
        text=normalized.text,
        title_query=title_query_with_requested_part(intent),
        issue_type=issue_type,
        candidates=[_issue_merge_candidate(candidate) for candidate in candidates],
        settings=settings,
    )


async def _choose_request_merge_id(
    *,
    session: Session,
    settings: Settings,
    group_id: int,
    intent: SupportIntent,
    normalized: NormalizedMessage,
    status: str,
    matched_show_id: int | None,
    matched_title: str | None,
) -> int | None:
    if not intent.title_query:
        return None
    deterministic = repositories.find_support_request_merge_candidate(
        session,
        group_id=group_id,
        title_query=title_query_with_requested_part(intent) or intent.title_query,
        status=status,
        category_hint=intent.category_hint,
        matched_show_id=matched_show_id,
        matched_title=matched_title,
    )
    if deterministic:
        return deterministic.id
    candidates = repositories.list_recent_support_requests(
        session,
        group_id=group_id,
        limit=12,
        status=status,
    )
    return await choose_support_merge_candidate_with_ai(
        kind="request",
        text=normalized.text,
        title_query=title_query_with_requested_part(intent) or intent.title_query,
        issue_type=None,
        candidates=[_request_merge_candidate(candidate) for candidate in candidates],
        settings=settings,
    )


def _issue_merge_candidate(issue: object) -> dict[str, object]:
    return {
        "id": issue.id,
        "issue_type": issue.issue_type,
        "title": issue.matched_title or issue.title_query,
        "message": issue.normalized_text[:180],
        "count": issue.occurrence_count,
    }


def _request_merge_candidate(request: object) -> dict[str, object]:
    return {
        "id": request.id,
        "title": request.matched_title or request.title_query,
        "message": request.normalized_text[:180],
        "count": request.occurrence_count,
    }


def _recent_group_context_texts(chat_id: int, current_text: str) -> list[str]:
    now = monotonic()
    bucket = _RECENT_GROUP_TEXTS[chat_id]
    while bucket and now - bucket[0][0] > _RECENT_CONTEXT_TTL_SECONDS:
        bucket.popleft()
    current_key = normalize_title_query(current_text).casefold()
    return [
        text
        for _, text in bucket
        if not current_key or normalize_title_query(text).casefold() != current_key
    ]


def _remember_group_context_text(chat_id: int, text: str) -> None:
    clean = normalize_title_query(text)
    if not _should_remember_group_context(raw_text=text, clean_text=clean):
        return
    _RECENT_GROUP_TEXTS[chat_id].append((monotonic(), clean[:600]))


def _should_remember_group_context(*, raw_text: str, clean_text: str) -> bool:
    if len(clean_text) < 3 or clean_text.startswith("/"):
        return False
    lower = raw_text.casefold()
    if any(
        token in lower
        for token in (
            "t.me/",
            "telegram.me/",
            "http://",
            "https://",
            "xxx",
            "nude",
            "naked",
            "watch hot",
            "onlyfans",
            "link expires",
        )
    ):
        return False
    return any(char.isalnum() for char in clean_text)


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


def _repeat_ban_threshold(settings: Settings) -> int:
    return max(0, settings.spam_repeat_ban_after)


def _maybe_escalate_repeat_violation(
    *,
    decision: Decision,
    sender: SenderContext,
    previous_violation_count: int,
    settings: Settings,
) -> Decision:
    threshold = _repeat_ban_threshold(settings)
    if threshold <= 0:
        return decision
    if not decision.delete or decision.ban:
        return decision
    if sender.user_id is None or sender.is_admin or sender.is_trusted:
        return decision
    if previous_violation_count + 1 < threshold:
        return decision
    return replace(
        decision,
        action="delete_and_ban",
        ban=True,
        pending_review=False,
        reason=f"repeat spam violation threshold reached ({threshold})",
    )


def _moderation_delete_notice_text(
    *,
    sender: SenderContext,
    violation_count: int,
    repeat_ban_after: int,
    banned: bool,
    ban_failed: bool,
) -> str:
    subject = _sender_public_label(sender)
    if banned:
        status = f"{subject} was banned after <b>{violation_count}</b> spam strikes."
    elif ban_failed:
        status = (
            f"{subject} hit the repeat-spam threshold, but I could not ban them yet. "
            "Check my ban/restrict permission."
        )
    elif repeat_ban_after > 0:
        remaining = max(0, repeat_ban_after - violation_count)
        if remaining <= 0:
            status = f"{subject} is at the ban threshold. Next cleanup may become a ban."
        elif remaining == 1:
            status = f"{subject} has <b>{violation_count}</b> strike. Next spam gets a ban."
        else:
            status = (
                f"{subject} has <b>{violation_count}</b> strike. "
                f"Ban threshold: <b>{repeat_ban_after}</b>."
            )
    else:
        status = f"{subject} has <b>{violation_count}</b> recorded spam strike."
    return f"<b>Spam neutralized.</b>\n{status}"


def _sender_public_label(sender: SenderContext) -> str:
    label = sender.display_name or (f"@{sender.username}" if sender.username else "The sender")
    if sender.user_id is not None:
        return f'<a href="tg://user?id={sender.user_id}">{escape(label)}</a>'
    return escape(label)


async def _send_moderation_delete_notice(
    *,
    bot: object,
    session: Session,
    settings: Settings,
    group_settings: object,
    chat_id: int,
    sender: SenderContext,
    violation_count: int,
    action_result: ActionResult,
) -> None:
    if not settings.moderation_delete_notice_enabled:
        return
    if (
        bool(getattr(group_settings, "silent_enabled", False))
        or getattr(group_settings, "mode", "") == "silent"
    ):
        return
    if action_result.delete_status != "ok":
        return
    text = _moderation_delete_notice_text(
        sender=sender,
        violation_count=violation_count,
        repeat_ban_after=_repeat_ban_threshold(settings),
        banned=action_result.ban_status == "ok",
        ban_failed=action_result.ban_status in {"failed", "missing_permission"},
    )
    await send_ephemeral_message(
        bot=bot,
        session=session,
        chat_id=chat_id,
        text=text,
        settings=settings,
        purpose="moderation_delete_notice",
        parse_mode="HTML",
        cleanup_seconds=settings.moderation_notice_cleanup_seconds,
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
    if auto_complete_authorized_group_setup(
        group=group,
        settings=settings,
        permissions=permissions,
    ):
        logger.info("Auto-completed setup for authorized chat %s", chat_id)

    user = getattr(message, "from_user", None)
    sender_user_id = getattr(user, "id", None)
    normalized = normalize_telegram_message(message)
    recent_context_texts = _recent_group_context_texts(chat_id, normalized.text)
    _remember_group_context_text(chat_id, normalized.text)
    if is_linked_channel_announcement(message):
        return PipelineResult(status="skipped_linked_channel_announcement")

    is_trusted = repositories.is_trusted_user(session, group.id, sender_user_id)
    previous_violation_count = repositories.get_violation_count(session, group.id, sender_user_id)
    previous_violation_score = repositories.get_violation_score(session, group.id, sender_user_id)
    sender = _message_sender_context(
        message=message,
        is_admin=sender_is_admin,
        is_trusted=is_trusted,
        previous_violation_score=previous_violation_score,
    )
    support_replied = False
    if sender.is_admin or sender.is_trusted:
        support_replied = await maybe_handle_support_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            group=group,
            normalized=normalized,
            sender_user_id=sender_user_id,
            recent_context_texts=recent_context_texts,
        )
        if support_replied:
            return PipelineResult(status="support_replied", support_replied=True)

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
    decision = _maybe_escalate_repeat_violation(
        decision=decision,
        sender=sender,
        previous_violation_count=previous_violation_count,
        settings=settings,
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
    violation_count = previous_violation_count
    if (decision.delete or decision.ban) and sender_user_id is not None:
        violation = repositories.record_violation(
            session,
            group_id=group.id,
            telegram_user_id=sender_user_id,
            action=decision.action,
            score=score.final_score,
        )
        violation_count = violation.violation_count

    if decision.delete:
        await _send_moderation_delete_notice(
            bot=bot,
            session=session,
            settings=settings,
            group_settings=group_settings,
            chat_id=chat_id,
            sender=sender,
            violation_count=violation_count,
            action_result=action_result,
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

    if not decision.delete and not decision.ban and ai_result.label == "not_spam":
        support_replied = await maybe_handle_support_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            group=group,
            normalized=normalized,
            sender_user_id=sender_user_id,
            recent_context_texts=recent_context_texts,
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
