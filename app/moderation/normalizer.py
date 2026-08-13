from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
URL_RE = re.compile(
    r"(?P<url>(?:https?://|www\.)[^\s<>()]+|(?:t|telegram)\.me/[^\s<>()]+)",
    re.IGNORECASE,
)
TELEGRAM_LINK_RE = re.compile(
    r"(?:https?://)?(?:t|telegram)\.me/[A-Za-z0-9_+/?=&.-]+", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    raw_text: str
    text: str
    raw_excerpt: str
    urls: list[str]
    domains: list[str]
    telegram_links: list[str]
    text_hash: str
    zero_width_count: int
    suspicious_unicode_count: int


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = unicodedata.normalize("NFKC", value)
    value = ZERO_WIDTH_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def text_hash(value: str) -> str:
    canonical = normalize_text(value).casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_urls(text: str, entities: list[object] | None = None) -> list[str]:
    found = [match.group("url").rstrip(".,);]\"'") for match in URL_RE.finditer(text)]
    if entities:
        for entity in entities:
            entity_type = getattr(entity, "type", None)
            if entity_type == "url":
                offset = int(getattr(entity, "offset", 0))
                length = int(getattr(entity, "length", 0))
                found.append(text[offset : offset + length])
            elif entity_type == "text_link" and getattr(entity, "url", None):
                found.append(entity.url)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in found:
        clean = url.strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            deduped.append(clean)
    return deduped


def domain_from_url(url: str) -> str | None:
    prepared = url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE) else f"https://{url}"
    parsed = urlparse(prepared)
    hostname = parsed.hostname
    if not hostname:
        return None
    hostname = hostname.lower().removeprefix("www.")
    return hostname.rstrip(".")


def extract_domains(urls: list[str]) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for url in urls:
        domain = domain_from_url(url)
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def extract_telegram_links(text: str, urls: list[str]) -> list[str]:
    candidates = [match.group(0).rstrip(".,);]\"'") for match in TELEGRAM_LINK_RE.finditer(text)]
    candidates.extend(url for url in urls if "t.me/" in url.lower() or "telegram.me/" in url.lower())
    links: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        clean = candidate.strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            links.append(clean)
    return links


def suspicious_unicode_count(value: str) -> int:
    count = 0
    for char in value:
        category = unicodedata.category(char)
        if category in {"Cf", "Co", "Cs"} or ord(char) > 127 and category.startswith(("M", "S")):
            count += 1
    return count


def normalize_message_parts(
    text: str | None = None,
    caption: str | None = None,
    entities: list[object] | None = None,
    caption_entities: list[object] | None = None,
    excerpt_length: int = 500,
) -> NormalizedMessage:
    raw = "\n".join(part for part in (text, caption) if part)
    normalized = normalize_text(raw)
    merged_entities: list[object] = []
    if entities:
        merged_entities.extend(entities)
    if caption_entities:
        merged_entities.extend(caption_entities)
    urls = extract_urls(normalized, merged_entities)
    domains = extract_domains(urls)
    telegram_links = extract_telegram_links(normalized, urls)
    return NormalizedMessage(
        raw_text=raw,
        text=normalized,
        raw_excerpt=normalized[:excerpt_length],
        urls=urls,
        domains=domains,
        telegram_links=telegram_links,
        text_hash=text_hash(normalized),
        zero_width_count=len(ZERO_WIDTH_RE.findall(raw)),
        suspicious_unicode_count=suspicious_unicode_count(raw),
    )


def normalize_telegram_message(message: object) -> NormalizedMessage:
    return normalize_message_parts(
        text=getattr(message, "text", None),
        caption=getattr(message, "caption", None),
        entities=getattr(message, "entities", None),
        caption_entities=getattr(message, "caption_entities", None),
    )
