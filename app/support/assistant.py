from __future__ import annotations

import random
import re
from dataclasses import dataclass
from html import escape

from app.config import Settings
from app.support.ibox_search import IboxItem, item_url, normalize_title_query, search_url

ISSUE_TYPES = {
    "broken_link": (
        "broken",
        "expired",
        "expire",
        "fix",
        "not working",
        "dead link",
        "invalid link",
        "link expired",
        "link issue",
        "please fix",
    ),
    "missing_episode": ("missing episode", "episode missing", "no episode", "missing ep"),
    "banned": ("banned", "copyright", "removed", "taken down", "takedown"),
    "playback": ("not playing", "cannot play", "won't play", "sound", "subtitles"),
}
ISSUE_LABELS = {
    "broken_link": "link problem",
    "missing_episode": "missing episode",
    "banned": "banned or removed item",
    "playback": "playback problem",
    "general": "issue",
}
ISSUE_REPLY_OPENERS = (
    "Logged this {label} for {title}. Tiny clipboard, serious business.",
    "Got it: {title} has a {label}. I have added it to the fix pile.",
    "{title} is now on the {label} list. Very glamorous admin paperwork.",
)
ISSUE_REPEAT_OPENERS = (
    "Already on it: {title} is still marked for a {label}. This is report #{count}.",
    "{title} is already on the fix pile for a {label}. Report #{count}, noted.",
    "Yep, {title} is already logged for a {label}. The complaint counter is now {count}.",
)
REQUEST_OPENERS = (
    "No sign of {title} on iBOX yet. I have filed it as a request.",
    "{title} is not in the catalog yet, so I have put it on the request pile.",
    "Could not find {title} yet. Request logged, clipboard mildly pleased.",
)
REQUEST_REPEAT_OPENERS = (
    "{title} is already on the request pile. That makes {count} people asking.",
    "Already got {title} in requests. Count is now {count}. Democracy, but with buffering.",
    "{title} is still pending in requests. This is vote #{count}.",
)
REQUEST_WORDS = (
    "request",
    "requesting",
    "need",
    "i need",
    "can i get",
    "send",
    "looking for",
    "find",
    "where can i",
    "where is",
    "do you have",
    "upload",
    "add",
    "search",
)
BARE_TITLE_BLOCKLIST = {
    "admin",
    "admins",
    "bro",
    "done",
    "good",
    "great",
    "hello",
    "hey",
    "hi",
    "lol",
    "nice",
    "no",
    "ok",
    "okay",
    "please",
    "pls",
    "seen",
    "thanks",
    "thank you",
    "this is good",
    "wow",
    "www",
    "yes",
}
TITLE_QUERY_BLOCKLIST = {
    "help",
    "it",
    "link",
    "links",
    "me",
    "movie",
    "please",
    "season",
    "series",
    "show",
    "subtitle",
    "subtitles",
    "that",
    "this",
}
HOWTO_WORDS = (
    "how to download",
    "how do i download",
    "how to play",
    "how do i play",
    "how to watch",
    "tutorial",
    "guide",
)
CATEGORY_HINTS = {
    "movie": ("movie", "film"),
    "anime": ("anime",),
    "tv": ("series", "season", "episode", "tv show", "show"),
}
STOP_PREFIXES = (
    "please",
    "pls",
    "plz",
    "hi",
    "hello",
    "can you",
    "could you",
    "can i get",
    "do you have",
    "where can i find",
    "where can i watch",
    "where is",
    "i need",
    "need",
    "requesting",
    "request for",
    "request",
    "send",
    "drop",
    "for",
    "upload",
    "add",
    "search for",
    "looking for",
    "link",
    "links",
)


@dataclass(frozen=True, slots=True)
class SupportIntent:
    kind: str
    title_query: str | None = None
    category_hint: str | None = None
    issue_type: str | None = None
    context_title: str | None = None


@dataclass(frozen=True, slots=True)
class SupportButton:
    text: str
    url: str | None = None
    callback_data: str | None = None


@dataclass(frozen=True, slots=True)
class SupportReply:
    text: str
    should_send_tutorial: bool = False
    allow_ai_rewrite: bool = True
    buttons: tuple[SupportButton, ...] = ()


def friendly_issue_label(issue_type: str | None) -> str:
    return ISSUE_LABELS.get(issue_type or "general", "issue")


def detect_support_intent(
    text: str,
    *,
    allow_bare_title: bool = False,
    context_title: str | None = None,
) -> SupportIntent | None:
    lower = text.casefold()
    incomplete_episode = extract_incomplete_episode_reference(text)
    if incomplete_episode:
        return SupportIntent(
            kind="clarify",
            title_query=incomplete_episode,
            category_hint="tv",
            context_title=context_title,
        )

    release_query = _extract_release_question(text)
    if release_query:
        return SupportIntent(
            kind="release",
            title_query=release_query,
            category_hint=_category_hint(lower) or "tv",
        )

    if any(_contains_phrase(lower, phrase) for phrase in HOWTO_WORDS):
        return SupportIntent(
            kind="howto",
            title_query=_extract_title_query(text),
            category_hint=_category_hint(lower),
        )

    for issue_type, phrases in ISSUE_TYPES.items():
        if any(_contains_phrase(lower, phrase) for phrase in phrases):
            return SupportIntent(
                kind="issue",
                title_query=_extract_title_query(text),
                category_hint=_category_hint(lower),
                issue_type=issue_type,
            )

    if any(_contains_phrase(lower, word) for word in REQUEST_WORDS):
        title_query = _extract_title_query(text)
        if title_query:
            return SupportIntent(
                kind="request",
                title_query=title_query,
                category_hint=_category_hint(lower),
            )
    if allow_bare_title:
        title_query = _extract_bare_title_query(text)
        if title_query:
            return SupportIntent(kind="bare_title", title_query=title_query)
    return None


def extract_incomplete_episode_reference(text: str) -> str | None:
    value = normalize_title_query(text.strip(" ?!.,:;\"'()[]{}"))
    if not value:
        return None
    if re.fullmatch(
        r"(?i)(?:season|series|s)\s*\d+(?:\s*(?:episode|ep|e)\s*\d+(?:\s*[-–]\s*\d+)?)?",
        value,
    ):
        return value
    if re.fullmatch(r"(?i)(?:episode|ep|e)\s*\d+(?:\s*[-–]\s*\d+)?", value):
        return value
    return None


def extract_support_title_query(text: str) -> str | None:
    return _extract_title_query(text)


def extract_support_context_title(text: str) -> str | None:
    value = re.sub(r"https?://\S+", " ", text)
    value = re.sub(
        r"\b(?:season|series)\s*\d+.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:episode|ep)\s*\d+(?:\s*[-–]\s*\d+)?.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:click\s+here|new\s+episode\s+update|new\s+episodes?|download|complete)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = normalize_title_query(value)
    if len(value) < 2:
        return None
    if value.casefold() in TITLE_QUERY_BLOCKLIST:
        return None
    return value


def _contains_phrase(lower_text: str, phrase: str) -> bool:
    escaped = re.escape(phrase.casefold()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", lower_text))


def _category_hint(lower: str) -> str | None:
    for category, hints in CATEGORY_HINTS.items():
        if any(hint in lower for hint in hints):
            return category
    return None


def _extract_title_query(text: str) -> str | None:
    value = re.sub(r"https?://\S+", " ", text)
    value = re.sub(
        r"\b(?:how\s+(?:to|do\s+i)\s+(?:download|play|watch)|tutorial|guide)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:click\s+here|new\s+episode\s+update|new\s+episodes?|updated?|download|"
        r"open|watch|complete|full\s+episode)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:broken|not\s+working|dead\s+link|invalid\s+link|missing\s+episode|"
        r"episode\s+missing|banned|copyright|removed|taken\s+down|not\s+playing|"
        r"cannot\s+play|won't\s+play|sound|subtitles?|expired|expire|please\s+fix|"
        r"fix|thanks)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:season|series)\s*\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bs\s*\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\b(?:episode|ep)\s*\d+(?:\s*[-–]\s*\d+)?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\be\s*\d+(?:\s*[-–]\s*\d+)?\b", " ", value, flags=re.IGNORECASE)
    value = normalize_title_query(value)
    lower = value.casefold()
    changed = True
    while changed:
        changed = False
        for prefix in STOP_PREFIXES:
            if lower.startswith(prefix):
                value = value[len(prefix) :].strip(" .:-")
                lower = value.casefold()
                changed = True
    value = re.sub(r"\s+(?:is|are)$", "", value, flags=re.IGNORECASE)
    value = normalize_title_query(value)
    value = re.sub(
        r"\b(?:movie|film|anime|series|season|episode|tv\s+show|show)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = normalize_title_query(value)
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    value = normalize_title_query(value)
    if len(value) < 2:
        return None
    if value.casefold() in TITLE_QUERY_BLOCKLIST:
        return None
    return value


def _extract_bare_title_query(text: str) -> str | None:
    if re.search(r"https?://|www\.|@\w+|[/#]", text, flags=re.IGNORECASE):
        return None
    value = normalize_title_query(text.strip(" ?!.,:;\"'()[]{}"))
    lower = value.casefold()
    if lower in BARE_TITLE_BLOCKLIST:
        return None
    if extract_incomplete_episode_reference(value):
        return None
    if not 3 <= len(value) <= 80:
        return None
    words = value.split()
    if not words or len(words) > 6:
        return None
    if len(words) == 1 and lower in BARE_TITLE_BLOCKLIST:
        return None
    if not any(char.isalnum() for char in value):
        return None
    return value


def _extract_release_question(text: str) -> str | None:
    lower = text.casefold()
    release_phrases = (
        "release date",
        "when will",
        "when is",
        "when does",
        "is it out",
        "is out",
        "released",
        "new season",
        "new episode",
        "next episode",
        "next season",
    )
    if not any(_contains_phrase(lower, phrase) for phrase in release_phrases):
        return None
    return _extract_title_query(text)


def build_support_reply(
    *,
    intent: SupportIntent,
    matches: list[IboxItem],
    settings: Settings,
    occurrence_count: int | None = None,
) -> SupportReply | None:
    if intent.kind == "clarify":
        quoted = escape(intent.title_query or "that season")
        if intent.context_title:
            context_title = escape(intent.context_title)
            query = f"{intent.context_title} {intent.title_query or ''}".strip()
            return SupportReply(
                text=(
                    "<b>Quick check</b>\n"
                    f"<blockquote>{quoted}</blockquote>\n"
                    f"Do you mean <b>{context_title}</b>? Tap search, or reply with the exact title "
                    "so I do not confidently run into the wrong wall."
                ),
                allow_ai_rewrite=False,
                buttons=(
                    SupportButton(
                        text="Search that",
                        url=search_url(settings, query, intent.category_hint),
                    ),
                    SupportButton(text="Tutorial", callback_data="support:tutorial"),
                ),
            )
        return SupportReply(
            text=(
                "<b>Quick check</b>\n"
                f"<blockquote>{quoted}</blockquote>\n"
                "Season of what title? Send the show name too, then I can search without "
                "acting like every Season 1 on earth is invited."
            ),
            allow_ai_rewrite=False,
            buttons=(SupportButton(text="Tutorial", callback_data="support:tutorial"),),
        )

    if intent.kind == "howto":
        return SupportReply(
            text=(
                "<b>iBOX quick route</b>\n"
                "Search the title, open the result, then tap <b>Download</b> on the item page.\n\n"
                f"<code>TV</code> {escape(settings.tvweb_site_base_url)}\n"
                f"<code>Anime</code> {escape(settings.tvweb_anime_base_url)}\n"
                f"<code>Movies</code> {escape(settings.tvweb_movies_base_url)}"
            ),
            should_send_tutorial=True,
            allow_ai_rewrite=False,
            buttons=(
                SupportButton(text="TV search", url=str(settings.tvweb_site_base_url)),
                SupportButton(text="Anime", url=str(settings.tvweb_anime_base_url)),
                SupportButton(text="Movies", url=str(settings.tvweb_movies_base_url)),
                SupportButton(text="Tutorial", callback_data="support:tutorial"),
                SupportButton(text="Solved", callback_data="support:solved"),
            ),
        )

    if intent.kind == "bare_title" and not matches:
        return None

    if intent.kind in {"request", "bare_title"}:
        if matches:
            query = escape(intent.title_query or "your search")
            lines = ["<b>Found on iBOX TV</b>", f"<blockquote>{query}</blockquote>"]
            buttons: list[SupportButton] = []
            for index, item in enumerate(matches[:3], start=1):
                url = item_url(settings, item)
                lines.append(
                    f"{index}. <b>{escape(item.display_title)}</b>\n"
                    f'   <a href="{escape(url, quote=True)}">Open on iBOX</a>'
                )
                buttons.append(SupportButton(text=f"Open {index}", url=url))
            buttons.extend(
                [
                    SupportButton(text="Tutorial", callback_data="support:tutorial"),
                    SupportButton(text="Solved", callback_data="support:solved"),
                    SupportButton(text="Still stuck", callback_data="support:stuck"),
                ]
            )
            return SupportReply(
                text="\n".join(lines),
                allow_ai_rewrite=False,
                buttons=tuple(buttons),
            )
        if intent.title_query:
            if not settings.tvweb_database_url:
                url = search_url(settings, intent.title_query, intent.category_hint)
                return SupportReply(
                    text=(
                        "<b>Search iBOX TV</b>\n"
                        f"<blockquote>{escape(intent.title_query)}</blockquote>\n"
                        "I cannot see the website database from here yet, so use the search button."
                    ),
                    allow_ai_rewrite=False,
                    buttons=(
                        SupportButton(text="Search iBOX", url=url),
                        SupportButton(text="Tutorial", callback_data="support:tutorial"),
                        SupportButton(text="Solved", callback_data="support:solved"),
                    ),
                )
            if occurrence_count and occurrence_count > 1:
                return SupportReply(
                    text=_format_variant(
                        REQUEST_REPEAT_OPENERS,
                        title=escape(intent.title_query),
                        count=str(occurrence_count),
                    )
                )
            return SupportReply(
                text=_format_variant(
                    REQUEST_OPENERS,
                    title=escape(intent.title_query),
                )
            )

    if intent.kind == "release":
        title = escape(intent.title_query or "that title")
        if matches:
            item = matches[0]
            url = item_url(settings, item)
            return SupportReply(
                text=(
                    "<b>Availability check</b>\n"
                    f"<blockquote>{title}</blockquote>\n"
                    f"I can see <b>{escape(item.display_title)}</b> in the iBOX catalog. "
                    "I do not have a live release-calendar feed connected yet, so I will not log "
                    "this as a broken-link issue.\n"
                    f'<a href="{escape(url, quote=True)}">Open the current iBOX item</a>'
                ),
            allow_ai_rewrite=False,
            buttons=(
                SupportButton(text="Open item", url=url),
                SupportButton(text="Solved", callback_data="support:solved"),
            ),
        )
        return SupportReply(
            text=(
                "<b>Availability check</b>\n"
                f"<blockquote>{title}</blockquote>\n"
                "I do not see it in the local iBOX catalog cache yet. This looks like an "
                "availability/release question, not a broken-link report, so I am not adding "
                "it to the fix dashboard."
            ),
            allow_ai_rewrite=False,
            buttons=(
                SupportButton(
                    text="Search iBOX",
                    url=search_url(settings, intent.title_query or "", intent.category_hint),
                ),
                SupportButton(text="Tutorial", callback_data="support:tutorial"),
                SupportButton(text="Solved", callback_data="support:solved"),
            ),
        )

    if intent.kind == "issue":
        label = friendly_issue_label(intent.issue_type)
        title = escape(matches[0].display_title if matches else intent.title_query or "that item")
        if occurrence_count and occurrence_count > 1:
            return SupportReply(
                text=_format_variant(
                    ISSUE_REPEAT_OPENERS,
                    label=escape(label),
                    title=title,
                    count=str(occurrence_count),
                )
            )
        if matches:
            return SupportReply(
                text=_format_variant(
                    ISSUE_REPLY_OPENERS,
                    label=escape(label),
                    title=title,
                )
            )
        return SupportReply(
            text=_format_variant(
                ISSUE_REPLY_OPENERS,
                label=escape(label),
                title=title,
            )
        )
    return None


def _format_variant(variants: tuple[str, ...], **values: str) -> str:
    return random.choice(variants).format(**values)
