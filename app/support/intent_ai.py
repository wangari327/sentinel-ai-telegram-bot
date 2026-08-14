from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings
from app.support.assistant import SupportIntent
from app.support.ibox_search import normalize_title_query
from app.support.responder import select_support_chat_config

KINDS = {"none", "request", "issue", "howto"}
CATEGORIES = {"movie", "tv", "anime"}
ISSUE_TYPES = {"broken_link", "missing_episode", "banned", "playback", "general"}


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
                    return intent
            except (KeyError, TypeError, ValueError, httpx.HTTPError):
                pass
            if attempt < chat_config.max_retries:
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "Repair the previous output. Return only valid JSON with "
                            "kind, confidence, title_query, category_hint, and issue_type."
                        ),
                    }
                )
    return None


def _messages(text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You classify Telegram group messages for an iBOX TV support assistant. "
                "The group is for TV shows, movies, anime, downloads, file-store bots, "
                "and reports about missing/broken/expired/banned content. "
                "Return JSON only. Schema: "
                '{"kind":"none|request|issue|howto","confidence":0.0,'
                '"title_query":null|string,"category_hint":null|"movie"|"tv"|"anime",'
                '"issue_type":null|"broken_link"|"missing_episode"|"banned"|"playback"|"general"}. '
                "Use request for title requests, including bare media titles like "
                "'Avatar', 'godzilla minus one', or 'requesting Shogun'. "
                "Use issue for broken/expired links, missing episodes, banned/removed items, "
                "playback/download complaints, or requests to fix a title. "
                "Use howto for asking how to download, play, search, use file-store bots, "
                "or use the website. Use none for greetings, thanks, admin bot notices, "
                "mode/status messages, username changes, spam reports from other bots, "
                "or normal conversation not asking for help. "
                "Extract title_query as the content title only, without filler words like "
                "'requesting', 'link', 'expired', 'please fix', or 'thanks'."
            ),
        },
        {
            "role": "user",
            "content": f"Message:\n{text}",
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
    if title and len(title) < 2:
        title = None

    category = data.get("category_hint")
    category_hint = str(category).strip().lower() if category else None
    if category_hint not in CATEGORIES:
        category_hint = None

    issue_value = data.get("issue_type")
    issue_type = str(issue_value).strip().lower() if issue_value else None
    if issue_type not in ISSUE_TYPES:
        issue_type = None

    if kind == "howto":
        return SupportIntent(kind="howto", title_query=title, category_hint=category_hint)
    if kind == "request" and title:
        return SupportIntent(kind="request", title_query=title, category_hint=category_hint)
    if kind == "issue":
        return SupportIntent(
            kind="issue",
            title_query=title,
            category_hint=category_hint,
            issue_type=issue_type or "general",
        )
    return None


def _choice_text(data: dict[str, Any]) -> str:
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        )
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
