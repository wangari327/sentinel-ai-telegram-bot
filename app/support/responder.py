from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import Any

import httpx

from app.config import Settings
from app.support.assistant import SupportIntent, SupportReply
from app.support.ibox_search import IboxItem

_URL_RE = re.compile(r"https?://[^\s<>()]+")


@dataclass(frozen=True, slots=True)
class SupportChatConfig:
    provider_name: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float
    max_retries: int


def select_support_chat_config(
    settings: Settings,
    *,
    require_ai_replies: bool = True,
) -> SupportChatConfig | None:
    if require_ai_replies and not settings.support_ai_replies:
        return None

    provider = settings.ai_provider
    if provider in {"openai_compatible", "compatible", "newapi", "hcnsec"}:
        if not settings.openai_compatible_api_key or not settings.openai_compatible_base_url:
            return None
        provider_name = settings.openai_compatible_provider_name or provider
        if provider in {"hcnsec", "newapi"} and provider_name == "openai_compatible":
            provider_name = provider
        return SupportChatConfig(
            provider_name=provider_name,
            api_key=settings.openai_compatible_api_key,
            base_url=settings.openai_compatible_base_url.rstrip("/"),
            model=settings.openai_compatible_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    if provider == "deepseek":
        if not settings.deepseek_api_key or not settings.deepseek_base_url:
            return None
        return SupportChatConfig(
            provider_name=settings.deepseek_provider_name,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url.rstrip("/"),
            model=settings.deepseek_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    if provider == "openai":
        if not settings.openai_api_key or not settings.openai_base_url:
            return None
        return SupportChatConfig(
            provider_name="openai",
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url.rstrip("/"),
            model=settings.openai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    if provider == "ollama":
        return SupportChatConfig(
            provider_name="ollama",
            api_key="",
            base_url=settings.ollama_base_url.rstrip("/"),
            model=settings.ollama_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    return None


async def render_support_reply(
    *,
    factual_reply: SupportReply,
    intent: SupportIntent,
    matches: list[IboxItem],
    settings: Settings,
    user_text: str,
) -> str:
    if not factual_reply.allow_ai_rewrite:
        return factual_reply.text

    chat_config = select_support_chat_config(settings)
    if chat_config is None:
        return factual_reply.text

    required_urls = _extract_urls(factual_reply.text)
    payload: dict[str, Any] = {
        "model": chat_config.model,
        "messages": _messages(
            factual_reply=factual_reply,
            intent=intent,
            matches=matches,
            settings=settings,
            user_text=user_text,
        ),
        "temperature": 0.75,
        "max_tokens": 180,
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
                rewritten = _clean_reply(_choice_text(response.json()))
                if _keeps_required_urls(rewritten, required_urls):
                    return escape(rewritten, quote=False)
            except (KeyError, TypeError, ValueError, httpx.HTTPError):
                pass
            if attempt < chat_config.max_retries:
                payload["messages"].append(
                    {
                        "role": "user",
                        "content": (
                            "Try again. Keep every URL exactly as provided, add no new links, "
                            "and return only the final Telegram reply."
                        ),
                    }
                )
    return factual_reply.text


def _messages(
    *,
    factual_reply: SupportReply,
    intent: SupportIntent,
    matches: list[IboxItem],
    settings: Settings,
    user_text: str,
) -> list[dict[str, str]]:
    matched_titles = [f"{item.display_title} ({item.category})" for item in matches[:3]]
    return [
        {
            "role": "system",
            "content": (
                "Rewrite Telegram group support replies for iBOX TV. Voice: "
                f"{settings.support_tone}. Be brief, chatty, and useful. Add a small "
                "human flourish when it fits, and vary the wording so replies do not "
                "feel copied from a form. Do not be mean. "
                "Do not use profanity, adult jokes, markdown tables, or 'as an AI'. "
                "Do not expose internal labels like broken_link or missing_episode. "
                "Do not invent availability, episode status, site behavior, admins, or links. "
                "Keep every URL exactly as provided and add no new URLs. "
                "Return only the message that should be sent to the group."
            ),
        },
        {
            "role": "user",
            "content": (
                "User message:\n"
                f"{user_text}\n\n"
                "Detected support intent:\n"
                f"kind={intent.kind}, title_query={intent.title_query}, "
                f"category_hint={intent.category_hint}, issue_type={intent.issue_type}\n\n"
                "Matched iBOX titles:\n"
                f"{matched_titles or 'none'}\n\n"
                "Facts that must stay true:\n"
                f"{factual_reply.text}\n\n"
                "Rewrite those facts in the requested voice."
            ),
        },
    ]


def _choice_text(data: dict[str, Any]) -> str:
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


def _clean_reply(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^```(?:text)?", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"```$", "", value).strip()
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value[:1200]


def _extract_urls(value: str) -> set[str]:
    return {url.rstrip(".,;:!?)\"'") for url in _URL_RE.findall(value)}


def _keeps_required_urls(rewritten: str, required_urls: set[str]) -> bool:
    if not rewritten:
        return False
    rewritten_urls = _extract_urls(rewritten)
    return required_urls.issubset(rewritten_urls) and rewritten_urls.issubset(required_urls)
