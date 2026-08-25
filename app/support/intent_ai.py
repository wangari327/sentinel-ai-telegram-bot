from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.config import Settings
from app.support.assistant import (
    SupportIntent,
    extract_season_episode_ranges,
    support_title_query_is_catalog_topic,
    support_title_query_is_allowed,
)
from app.support.ibox_search import normalize_title_query
from app.support.responder import select_support_chat_config

KINDS = {"none", "request", "issue", "howto", "release"}
CATEGORIES = {"movie", "tv", "anime"}
ISSUE_TYPES = {"broken_link", "missing_episode", "banned", "playback", "general"}
LOG_VET_ACTIONS = {"log", "retry_search", "clarify", "skip"}


@dataclass(frozen=True, slots=True)
class SupportLogVet:
    action: str
    confidence: float
    corrected_title_query: str | None = None
    reason: str | None = None


async def classify_support_intent_with_ai(
    *,
    text: str,
    settings: Settings,
) -> SupportIntent | None:
    if not settings.support_ai_intent_enabled:
        return None
    chat_config = select_support_chat_config(settings, require_ai_replies=False)
    if chat_config is None:
        return None

    payload: dict[str, Any] = {
        "model": chat_config.model,
        "messages": _messages(text[: settings.support_ai_intent_max_text_chars]),
        "temperature": 0,
        "max_tokens": 220,
    }
    headers = {"Content-Type": "application/json"}
    if chat_config.api_key:
        headers["Authorization"] = f"Bearer {chat_config.api_key}"

    async with httpx.AsyncClient(timeout=chat_config.timeout_seconds) as client:
        for attempt in range(chat_config.max_retries + 1):
            try:
                response = await client.post(
                    f"{chat_config.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = _parse_json(_choice_text(response.json()))
                intent = _intent_from_data(data, settings=settings)
                if intent:
                    (
                        season_number,
                        season_end_number,
                        episode_number,
                        episode_end_number,
                    ) = extract_season_episode_ranges(text)
                    return replace(
                        intent,
                        season_number=intent.season_number or season_number,
                        season_end_number=intent.season_end_number or season_end_number,
                        episode_number=intent.episode_number or episode_number,
                        episode_end_number=intent.episode_end_number or episode_end_number,
                    )
            except (KeyError, TypeError, ValueError, httpx.HTTPError):
                pass
            if attempt < chat_config.max_retries:
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "Repair the previous output. Return only valid JSON with "
                            "kind, confidence, title_query, category_hint, issue_type, "
                            "season_number, season_end_number, episode_number, "
                            "and episode_end_number."
                        ),
                    }
                )
    return None


async def choose_support_merge_candidate_with_ai(
    *,
    kind: str,
    text: str,
    title_query: str | None,
    issue_type: str | None,
    candidates: list[dict[str, object]],
    settings: Settings,
) -> int | None:
    if not settings.support_ai_intent_enabled or not candidates:
        return None
    chat_config = select_support_chat_config(settings, require_ai_replies=False)
    if chat_config is None:
        return None

    trimmed_candidates = candidates[:12]
    payload: dict[str, Any] = {
        "model": chat_config.model,
        "messages": _merge_messages(
            kind=kind,
            text=text[: settings.support_ai_intent_max_text_chars],
            title_query=title_query,
            issue_type=issue_type,
            candidates=trimmed_candidates,
        ),
        "temperature": 0,
        "max_tokens": 140,
    }
    headers = {"Content-Type": "application/json"}
    if chat_config.api_key:
        headers["Authorization"] = f"Bearer {chat_config.api_key}"

    async with httpx.AsyncClient(timeout=chat_config.timeout_seconds) as client:
        try:
            response = await client.post(
                f"{chat_config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = _parse_json(_choice_text(response.json()))
        except (KeyError, TypeError, ValueError, httpx.HTTPError):
            return None
    return _merge_candidate_from_data(data, candidates=trimmed_candidates, settings=settings)


async def vet_support_log_with_ai(
    *,
    kind: str,
    text: str,
    intent: SupportIntent,
    availability_title: str | None,
    availability_state: str | None,
    settings: Settings,
) -> SupportLogVet | None:
    if not settings.support_ai_intent_enabled:
        return None
    chat_config = select_support_chat_config(settings, require_ai_replies=False)
    if chat_config is None:
        return None

    payload: dict[str, Any] = {
        "model": chat_config.model,
        "messages": _log_vet_messages(
            kind=kind,
            text=text[: settings.support_ai_intent_max_text_chars],
            intent=intent,
            availability_title=availability_title,
            availability_state=availability_state,
        ),
        "temperature": 0,
        "max_tokens": 180,
    }
    headers = {"Content-Type": "application/json"}
    if chat_config.api_key:
        headers["Authorization"] = f"Bearer {chat_config.api_key}"

    async with httpx.AsyncClient(timeout=chat_config.timeout_seconds) as client:
        try:
            response = await client.post(
                f"{chat_config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = _parse_json(_choice_text(response.json()))
        except (KeyError, TypeError, ValueError, httpx.HTTPError):
            return None
    return _log_vet_from_data(data, settings=settings)


def _messages(text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You classify Telegram group messages for an iBOX TV support assistant. "
                "The group is for TV shows, movies, anime, downloads, file-store bots, "
                "and reports about missing/broken/expired/banned content. "
                "Return JSON only. Schema: "
                '{"kind":"none|request|issue|howto|release","confidence":0.0,'
                '"title_query":null|string,"category_hint":null|"movie"|"tv"|"anime",'
                '"issue_type":null|"broken_link"|"missing_episode"|"banned"|"playback"|"general",'
                '"season_number":null|number,"season_end_number":null|number,'
                '"episode_number":null|number,"episode_end_number":null|number}. '
                "Use request for title requests, including bare media titles like "
                "'Avatar', 'godzilla minus one', or 'requesting Shogun'. "
                "Use issue for broken/expired links, missing episodes, banned/removed items, "
                "playback/download complaints, or requests to fix a title. "
                "Use release for release-date or future-episode questions such as "
                "'when is season 2 out' or 'next episode release date'. "
                "Use howto for asking how to download, play, search, use file-store bots, "
                "or use the website. Also use howto, not request, for category/browsing "
                "questions like 'do u have reality shows', 'any web series', or 'where "
                "are movies'. Use none for greetings, thanks, admin bot notices, "
                "mode/status messages, username changes, spam reports from other bots, "
                "or incomplete episode-only messages like 'Season 1' without a title. "
                "Use none for normal conversation not asking for help. "
                "Extract title_query as the content title only, without filler words like "
                "'requesting', 'link', 'expired', 'please fix', or 'thanks'. Extract "
                "season_number and episode_number when the user names them."
            ),
        },
        {
            "role": "user",
            "content": f"Message:\n{text}",
        },
    ]


def _merge_messages(
    *,
    kind: str,
    text: str,
    title_query: str | None,
    issue_type: str | None,
    candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You decide whether a new iBOX TV support report should merge into an "
                "existing open dashboard item. Return JSON only: "
                '{"candidate_id":null|number,"confidence":0.0,"reason":"short"}. '
                "Merge only when they refer to the same underlying movie/show/anime and "
                "the same practical request or issue. Treat title variants, season/episode "
                "suffixes, spelling/case differences, and 'fix link' vs 'expired link' as "
                "mergeable. Do not merge different titles or different problem types."
            ),
        },
        {
            "role": "user",
            "content": (
                f"New item kind={kind}, title_query={title_query}, issue_type={issue_type}\n"
                f"New message:\n{text}\n\n"
                f"Existing candidates:\n{json.dumps(candidates, ensure_ascii=False)}"
            ),
        },
    ]


def _log_vet_messages(
    *,
    kind: str,
    text: str,
    intent: SupportIntent,
    availability_title: str | None,
    availability_state: str | None,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the final quality gate before an iBOX TV Telegram bot writes an "
                "unresolved item to the owner dashboard. Return JSON only. Schema: "
                '{"action":"log|retry_search|clarify|skip","confidence":0.0,'
                '"corrected_title_query":null|string,"reason":"short"}. '
                "Use log only when the user's own message clearly asks for a missing "
                "movie/show/anime or reports a real issue, and the extracted title is "
                "probably correct. Use retry_search when the extracted title is probably "
                "an alias, subtitle, franchise fragment, typo, or parser miss; put the "
                "best corrected catalog search phrase in corrected_title_query. Use "
                "clarify when the user intent is real but the title or season context is "
                "too ambiguous. Use skip for chatter, admin/status/result-list messages, "
                "or cases that should not create dashboard work. If TMDB gives a canonical "
                "title that differs from the extracted query, prefer retry_search before "
                "logging. Do not add items just because search failed."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Kind about to be logged: {kind}\n"
                f"User message:\n{text}\n\n"
                "Extracted intent:\n"
                f"title_query={intent.title_query}, category_hint={intent.category_hint}, "
                f"issue_type={intent.issue_type}, context_title={intent.context_title}, "
                f"season_number={intent.season_number}, season_end_number={intent.season_end_number}, "
                f"episode_number={intent.episode_number}, episode_end_number={intent.episode_end_number}\n\n"
                f"TMDB canonical title: {availability_title or 'none'}\n"
                f"TMDB availability state: {availability_state or 'none'}"
            ),
        },
    ]


def _intent_from_data(data: dict[str, Any], *, settings: Settings) -> SupportIntent | None:
    confidence = float(data.get("confidence") or 0)
    if confidence < settings.support_ai_intent_threshold:
        return None

    kind = str(data.get("kind") or "none").strip().lower()
    if kind not in KINDS or kind == "none":
        return None

    title_query = data.get("title_query")
    title = normalize_title_query(str(title_query)) if title_query else None
    if title and (len(title) < 2 or not support_title_query_is_allowed(title)):
        title = None
    if kind == "request" and title and support_title_query_is_catalog_topic(title):
        kind = "howto"

    category = data.get("category_hint")
    category_hint = str(category).strip().lower() if category else None
    if category_hint not in CATEGORIES:
        category_hint = None

    issue_value = data.get("issue_type")
    issue_type = str(issue_value).strip().lower() if issue_value else None
    if issue_type not in ISSUE_TYPES:
        issue_type = None

    season_number = _optional_int(data.get("season_number"))
    episode_number = _optional_int(data.get("episode_number"))
    season_end_number = _optional_int(data.get("season_end_number"))
    episode_end_number = _optional_int(data.get("episode_end_number"))

    if kind == "howto":
        return SupportIntent(
            kind="howto",
            title_query=title,
            category_hint=category_hint,
            season_number=season_number,
            season_end_number=season_end_number,
            episode_number=episode_number,
            episode_end_number=episode_end_number,
        )
    if kind == "request" and title:
        return SupportIntent(
            kind="request",
            title_query=title,
            category_hint=category_hint,
            season_number=season_number,
            season_end_number=season_end_number,
            episode_number=episode_number,
            episode_end_number=episode_end_number,
        )
    if kind == "release" and title:
        return SupportIntent(
            kind="release",
            title_query=title,
            category_hint=category_hint,
            season_number=season_number,
            season_end_number=season_end_number,
            episode_number=episode_number,
            episode_end_number=episode_end_number,
        )
    if kind == "issue":
        return SupportIntent(
            kind="issue",
            title_query=title,
            category_hint=category_hint,
            issue_type=issue_type or "general",
            season_number=season_number,
            season_end_number=season_end_number,
            episode_number=episode_number,
            episode_end_number=episode_end_number,
        )
    return None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merge_candidate_from_data(
    data: dict[str, Any],
    *,
    candidates: list[dict[str, object]],
    settings: Settings,
) -> int | None:
    confidence = float(data.get("confidence") or 0)
    if confidence < max(settings.support_ai_intent_threshold, 0.74):
        return None
    candidate_id = data.get("candidate_id")
    if candidate_id is None:
        return None
    try:
        selected = int(candidate_id)
    except (TypeError, ValueError):
        return None
    valid_ids = {
        int(candidate["id"]) for candidate in candidates if candidate.get("id") is not None
    }
    return selected if selected in valid_ids else None


def _log_vet_from_data(data: dict[str, Any], *, settings: Settings) -> SupportLogVet | None:
    action = str(data.get("action") or "").strip().lower()
    if action not in LOG_VET_ACTIONS:
        return None
    confidence = float(data.get("confidence") or 0)
    if confidence < 0.55:
        return None
    corrected_value = data.get("corrected_title_query")
    corrected = normalize_title_query(str(corrected_value)) if corrected_value else None
    if corrected and (len(corrected) < 2 or not support_title_query_is_allowed(corrected)):
        corrected = None
    if action == "retry_search" and not corrected:
        action = "clarify"
    if action == "log" and confidence < settings.support_ai_intent_threshold:
        return None
    reason_value = data.get("reason")
    reason = str(reason_value).strip()[:220] if reason_value else None
    return SupportLogVet(
        action=action,
        confidence=confidence,
        corrected_title_query=corrected,
        reason=reason,
    )


def _choice_text(data: dict[str, Any]) -> str:
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def _parse_json(value: str) -> dict[str, Any]:
    value = value.strip()
    value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise TypeError("support intent response must be a JSON object")
    return parsed
