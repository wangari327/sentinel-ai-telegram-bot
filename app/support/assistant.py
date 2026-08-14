from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from html import escape

from app.config import Settings
from app.support.ibox_search import IboxItem, item_url, normalize_title_query, search_url
from app.support.tmdb import TmdbAvailability

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
    "when does",
    "when is",
    "when will",
)
POLITE_SUFFIXES = ("please", "pls", "plz", "thanks", "thank you")


@dataclass(frozen=True, slots=True)
class SupportIntent:
    kind: str
    title_query: str | None = None
    category_hint: str | None = None
    issue_type: str | None = None
    context_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None


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
    season_number, episode_number = extract_season_episode_numbers(text)
    incomplete_episode = extract_incomplete_episode_reference(text)
    if incomplete_episode:
        return SupportIntent(
            kind="clarify",
            title_query=incomplete_episode,
            category_hint="tv",
            context_title=context_title,
            season_number=season_number,
            episode_number=episode_number,
        )

    release_query = _extract_release_question(text)
    if release_query:
        return SupportIntent(
            kind="release",
            title_query=release_query,
            category_hint=_category_hint(lower) or "tv",
            season_number=season_number,
            episode_number=episode_number,
        )

    if any(_contains_phrase(lower, phrase) for phrase in HOWTO_WORDS):
        return SupportIntent(
            kind="howto",
            title_query=_extract_title_query(text),
            category_hint=_category_hint(lower),
            season_number=season_number,
            episode_number=episode_number,
        )

    if _looks_like_missing_episode_issue(lower):
        return SupportIntent(
            kind="issue",
            title_query=_extract_title_query(text),
            category_hint=_category_hint(lower) or "tv",
            issue_type="missing_episode",
            season_number=season_number,
            episode_number=episode_number,
        )

    for issue_type, phrases in ISSUE_TYPES.items():
        if any(_contains_phrase(lower, phrase) for phrase in phrases):
            return SupportIntent(
                kind="issue",
                title_query=_extract_title_query(text),
                category_hint=_category_hint(lower),
                issue_type=issue_type,
                season_number=season_number,
                episode_number=episode_number,
            )

    if any(_contains_phrase(lower, word) for word in REQUEST_WORDS):
        title_query = _extract_title_query(text)
        if title_query:
            return SupportIntent(
                kind="request",
                title_query=title_query,
                category_hint=_category_hint(lower),
                season_number=season_number,
                episode_number=episode_number,
            )
    if allow_bare_title:
        title_query = _extract_bare_title_query(text)
        if title_query:
            if season_number is not None or episode_number is not None:
                title_query = _extract_title_query(text) or title_query
            category_hint = _category_hint(lower) or ("tv" if season_number else None)
            return SupportIntent(
                kind=_bare_title_kind(
                    text=text,
                    title_query=title_query,
                    category_hint=category_hint,
                    season_number=season_number,
                    episode_number=episode_number,
                ),
                title_query=title_query,
                category_hint=category_hint,
                season_number=season_number,
                episode_number=episode_number,
            )
    return None


def extract_season_episode_numbers(text: str) -> tuple[int | None, int | None]:
    season_number: int | None = None
    episode_number: int | None = None
    compact_match = re.search(r"(?i)\bs0*(\d{1,3})\s*e0*(\d{1,4})\b", text)
    season_match = re.search(r"(?i)\b(?:season|series|s)\s*0*(\d{1,3})\b", text)
    if compact_match:
        season_number = int(compact_match.group(1))
        episode_number = int(compact_match.group(2))
    if season_number is None and season_match:
        season_number = int(season_match.group(1))
    episode_match = re.search(
        r"(?i)\b(?:episode|ep)\s*0*(\d{1,4})(?:\s*(?:-|\u2013)\s*\d{1,4})?\b",
        text,
    )
    short_episode_match = re.search(r"(?i)\be0*(\d{1,4})\b", text)
    if episode_number is None and episode_match:
        episode_number = int(episode_match.group(1))
    elif episode_number is None and short_episode_match:
        episode_number = int(short_episode_match.group(1))
    return season_number, episode_number


def extract_incomplete_episode_reference(text: str) -> str | None:
    value = normalize_title_query(text.strip(" ?!.,:;\"'()[]{}"))
    if not value:
        return None
    if re.fullmatch(
        r"(?i)(?:season|series|s)\s*\d+(?:\s*(?:episode|ep|e)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?)?",
        value,
    ):
        return value
    if re.fullmatch(r"(?i)(?:episode|ep|e)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?", value):
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
        r"\b(?:episode|ep)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?.*$",
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
    value = _strip_polite_suffixes(normalize_title_query(value))
    if len(value) < 2:
        return None
    if value.casefold() in TITLE_QUERY_BLOCKLIST:
        return None
    return value


def _contains_phrase(lower_text: str, phrase: str) -> bool:
    escaped = re.escape(phrase.casefold()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<!\w){escaped}(?!\w)", lower_text))


def _looks_like_missing_episode_issue(lower_text: str) -> bool:
    return bool(
        re.search(
            r"\bmissing\s+(?:episode|ep|e)\s*\d+\b"
            r"|\b(?:episode|ep|e)\s*\d+\b.{0,24}\b(?:missing|not\s+there|not\s+available)\b",
            lower_text,
        )
    )


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
        r"\bmissing\s+(?:episode|ep|e)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:episode|ep|e)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?\s+"
        r"(?:missing|not\s+there|not\s+available)\b",
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
    value = re.sub(
        r"\bs\d{1,3}\s*e\d{1,4}(?:\s*(?:-|\u2013)\s*\d{1,4})?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:season|series)\s*\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bs\s*\d+\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\b(?:episode|ep)\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\be\s*\d+(?:\s*(?:-|\u2013)\s*\d+)?\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = _strip_polite_suffixes(normalize_title_query(value))
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
    value = re.sub(
        r"\s+(?:out|released|available|coming|coming\s+out)$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = _strip_polite_suffixes(normalize_title_query(value))
    value = re.sub(
        r"\b(?:movie|film|anime|series|season|episode|tv\s+show|show)\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = _strip_polite_suffixes(normalize_title_query(value))
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
    value = _strip_polite_suffixes(normalize_title_query(text.strip(" ?!.,:;\"'()[]{}")))
    lower = value.casefold()
    if lower in BARE_TITLE_BLOCKLIST:
        return None
    if extract_incomplete_episode_reference(value):
        return None
    category_hint = _category_hint(lower)
    if category_hint:
        stripped = _extract_title_query(value)
        if stripped and _valid_bare_title_candidate(stripped, allow_short=True):
            return stripped
    if not 3 <= len(value) <= 80:
        return None
    if not _valid_bare_title_candidate(value):
        return None
    return value


def _valid_bare_title_candidate(value: str, *, allow_short: bool = False) -> bool:
    lower = value.casefold()
    min_length = 2 if allow_short else 3
    if not min_length <= len(value) <= 80:
        return False
    words = value.split()
    if not words or len(words) > 6:
        return False
    if lower in BARE_TITLE_BLOCKLIST or lower in TITLE_QUERY_BLOCKLIST:
        return False
    if len(words) == 1 and lower in BARE_TITLE_BLOCKLIST:
        return False
    return any(char.isalnum() for char in value)


def _strip_polite_suffixes(value: str) -> str:
    changed = True
    while changed:
        changed = False
        for suffix in POLITE_SUFFIXES:
            next_value = re.sub(
                rf"\s+{re.escape(suffix)}$",
                "",
                value,
                flags=re.IGNORECASE,
            ).strip(" .:-")
            if next_value != value:
                value = next_value
                changed = True
    return value


def _bare_title_kind(
    *,
    text: str,
    title_query: str,
    category_hint: str | None,
    season_number: int | None,
    episode_number: int | None,
) -> str:
    if season_number is not None or episode_number is not None:
        return "request"
    if category_hint:
        return "request"
    if re.search(r"\b(?:19|20)\d{2}\b", title_query):
        return "request"
    if re.search(r"\b(?:please|pls|plz)\b", text, re.IGNORECASE):
        return "request"
    if re.search(r"\b(?:movie|film|series|anime|tv\s+show|show)\b", text, re.IGNORECASE):
        return "request"
    return "bare_title"


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


def filter_matches_for_requested_part(
    matches: list[IboxItem],
    intent: SupportIntent,
) -> list[IboxItem]:
    if intent.season_number is None and intent.episode_number is None:
        return matches
    filtered = [item for item in matches if _item_matches_requested_part(item, intent)]
    return filtered


def _item_matches_requested_part(item: IboxItem, intent: SupportIntent) -> bool:
    value = normalize_title_query(
        " ".join(
            part
            for part in (
                item.title,
                item.episode_title,
                item.display_title,
            )
            if part
        )
    ).casefold()
    if intent.season_number is not None and not _season_matches_value(value, intent.season_number):
        return False
    return intent.episode_number is None or _episode_matches_value(value, intent.episode_number)


def _season_matches_value(value: str, season_number: int) -> bool:
    season = re.escape(str(season_number))
    patterns = (
        rf"\bseason\s*0?{season}\b",
        rf"\bseries\s*0?{season}\b",
        rf"\bs\s*0?{season}(?:\b|e\d{{1,4}}\b)",
    )
    return any(re.search(pattern, value) for pattern in patterns)


def _episode_matches_value(value: str, episode_number: int) -> bool:
    for pattern in (
        r"\b(?:episode|ep|e)\s*0*(\d{1,4})(?:\s*(?:-|\u2013)\s*0*(\d{1,4}))?\b",
        r"\bs\d{1,3}\s*e0*(\d{1,4})(?:\s*(?:-|\u2013)\s*0*(\d{1,4}))?\b",
    ):
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if start <= episode_number <= end:
                return True
    return False


def title_query_with_requested_part(intent: SupportIntent) -> str | None:
    if not intent.title_query:
        return None
    part = _requested_part_label(intent)
    if not part:
        return intent.title_query
    return f"{intent.title_query} {part}"


def availability_blocks_logging(
    intent: SupportIntent,
    availability: TmdbAvailability | None,
    *,
    today: date | None = None,
) -> bool:
    if availability is None:
        return False
    state = availability.state(today)
    if intent.kind == "release":
        return True
    future_or_not_ready = {
        "future_movie",
        "future_tv",
        "future_season",
        "future_episode",
        "season_unconfirmed",
        "episode_unlisted",
        "unknown_episode_date",
        "unknown_season_date",
    }
    if intent.kind == "request" and state in future_or_not_ready:
        return True
    if intent.kind == "issue" and intent.issue_type == "missing_episode":
        return state in future_or_not_ready
    return False


def build_availability_reply(
    *,
    intent: SupportIntent,
    matches: list[IboxItem],
    settings: Settings,
    availability: TmdbAvailability | None,
    today: date | None = None,
) -> SupportReply | None:
    if availability is None:
        return None
    state = availability.state(today)
    title = escape(availability.title or intent.title_query or "that title")
    requested = escape(_requested_part_label(intent) or "availability")
    buttons = _availability_buttons(settings=settings, matches=matches, availability=availability)
    if not availability.found:
        if intent.kind != "release":
            return None
        return SupportReply(
            text=(
                "<b>Availability check</b>\n"
                f"<blockquote>{escape(intent.title_query or 'that title')}</blockquote>\n"
                "I could not confirm this one on TMDB, so I am not going to invent a "
                "release date with a straight face."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )

    if state == "future_movie":
        return SupportReply(
            text=(
                "<b>Not out yet</b>\n"
                f"<blockquote>{title}</blockquote>\n"
                f"TMDB lists the movie release date as <b>{_date_text(availability.release_date)}</b>. "
                "So no, this is not a broken iBOX link. Time itself is the bottleneck. Rude."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state == "future_tv":
        return SupportReply(
            text=(
                "<b>Not out yet</b>\n"
                f"<blockquote>{title}</blockquote>\n"
                f"TMDB says the show starts on <b>{_date_text(availability.first_air_date)}</b>. "
                "I will not log that as an iBOX problem."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state == "future_season":
        return SupportReply(
            text=(
                "<b>Season not aired yet</b>\n"
                f"<blockquote>{title} - {requested}</blockquote>\n"
                f"TMDB lists this season for <b>{_date_text(availability.season_air_date)}</b>. "
                "No dashboard noise from me."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state == "future_episode":
        episode_name = (
            f" - {escape(availability.episode_name)}" if availability.episode_name else ""
        )
        return SupportReply(
            text=(
                "<b>Episode not aired yet</b>\n"
                f"<blockquote>{title} - {requested}{episode_name}</blockquote>\n"
                f"TMDB has the air date as <b>{_date_text(availability.episode_air_date)}</b>. "
                "The fix team cannot repair the future. Annoying, but tidy."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state == "season_unconfirmed":
        return SupportReply(
            text=(
                "<b>No confirmed season yet</b>\n"
                f"<blockquote>{title} - {requested}</blockquote>\n"
                "TMDB does not list that season. I am not logging it as missing on iBOX "
                "until the season actually exists somewhere outside our wishes."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state == "episode_unlisted":
        count_text = (
            f" TMDB currently lists <b>{availability.season_episode_count}</b> episode(s) "
            "for that season."
            if availability.season_episode_count is not None
            else ""
        )
        return SupportReply(
            text=(
                "<b>Episode not listed</b>\n"
                f"<blockquote>{title} - {requested}</blockquote>\n"
                f"TMDB does not list that episode yet.{count_text} "
                "I am keeping this out of the broken-link pile."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if state in {"unknown_episode_date", "unknown_season_date"}:
        return SupportReply(
            text=(
                "<b>Release date unclear</b>\n"
                f"<blockquote>{title} - {requested}</blockquote>\n"
                "TMDB knows the title, but it does not have a usable air date for that part yet. "
                "I am not logging it as an iBOX issue."
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    if intent.kind == "release":
        date_value = (
            availability.episode_air_date
            or availability.season_air_date
            or availability.release_date
            or availability.first_air_date
        )
        status = (
            f"It is listed as released/aired on <b>{_date_text(date_value)}</b>."
            if date_value
            else f"TMDB status: <code>{escape(availability.status or 'unknown')}</code>."
        )
        return SupportReply(
            text=(
                "<b>Availability check</b>\n"
                f"<blockquote>{title} - {requested}</blockquote>\n"
                f"{status}"
            ),
            allow_ai_rewrite=False,
            buttons=buttons,
        )
    return None


def build_support_reply(
    *,
    intent: SupportIntent,
    matches: list[IboxItem],
    settings: Settings,
    occurrence_count: int | None = None,
    availability: TmdbAvailability | None = None,
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
            lines = ["<b>Found on ibox-tv.com</b>", f"<blockquote>{query}</blockquote>"]
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
            if availability and availability.found:
                state = availability.state()
                if state in {
                    "released_movie",
                    "released_tv",
                    "aired_season",
                    "aired_episode",
                    "unknown_movie_date",
                    "unknown_tv_date",
                }:
                    title = escape(availability.title or intent.title_query)
                    date_value = (
                        availability.episode_air_date
                        or availability.season_air_date
                        or availability.release_date
                        or availability.first_air_date
                    )
                    date_line = (
                        f"\nTMDB date: <b>{_date_text(date_value)}</b>." if date_value else ""
                    )
                    count_line = (
                        f"\nRequest count: <b>{occurrence_count}</b>."
                        if occurrence_count and occurrence_count > 1
                        else ""
                    )
                    return SupportReply(
                        text=(
                            "<b>Request logged</b>\n"
                            f"<blockquote>{title} - {escape(_requested_part_label(intent) or 'full title')}</blockquote>\n"
                            f"TMDB says this exists, but I do not see the requested part in iBOX yet."
                            f"{date_line}{count_line}"
                        ),
                        allow_ai_rewrite=False,
                        buttons=_availability_buttons(
                            settings=settings,
                            matches=matches,
                            availability=availability,
                        ),
                    )
            if occurrence_count and occurrence_count > 1:
                return SupportReply(
                    text=_format_variant(
                        REQUEST_REPEAT_OPENERS,
                        title=escape(title_query_with_requested_part(intent) or intent.title_query),
                        count=str(occurrence_count),
                    ),
                    buttons=(
                        SupportButton(
                            text="Search iBOX",
                            url=search_url(settings, intent.title_query, intent.category_hint),
                        ),
                        SupportButton(text="Tutorial", callback_data="support:tutorial"),
                    ),
                )
            return SupportReply(
                text=_format_variant(
                    REQUEST_OPENERS,
                    title=escape(title_query_with_requested_part(intent) or intent.title_query),
                ),
                buttons=(
                    SupportButton(
                        text="Search iBOX",
                        url=search_url(settings, intent.title_query, intent.category_hint),
                    ),
                    SupportButton(text="Tutorial", callback_data="support:tutorial"),
                ),
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
        title = escape(
            matches[0].display_title
            if matches
            else title_query_with_requested_part(intent) or intent.title_query or "that item"
        )
        if occurrence_count and occurrence_count > 1:
            return SupportReply(
                text=_format_variant(
                    ISSUE_REPEAT_OPENERS,
                    label=escape(label),
                    title=title,
                    count=str(occurrence_count),
                ),
                buttons=(SupportButton(text="Solved", callback_data="support:solved"),),
            )
        if matches:
            return SupportReply(
                text=_format_variant(
                    ISSUE_REPLY_OPENERS,
                    label=escape(label),
                    title=title,
                ),
                buttons=(
                    SupportButton(text="Open iBOX", url=item_url(settings, matches[0])),
                    SupportButton(text="Solved", callback_data="support:solved"),
                ),
            )
        return SupportReply(
            text=_format_variant(
                ISSUE_REPLY_OPENERS,
                label=escape(label),
                title=title,
            ),
            buttons=(
                SupportButton(
                    text="Search iBOX",
                    url=search_url(settings, intent.title_query or "", intent.category_hint),
                ),
                SupportButton(text="Solved", callback_data="support:solved"),
            ),
        )
    return None


def _availability_buttons(
    *,
    settings: Settings,
    matches: list[IboxItem],
    availability: TmdbAvailability,
) -> tuple[SupportButton, ...]:
    buttons: list[SupportButton] = []
    if matches:
        buttons.append(SupportButton(text="Open iBOX", url=item_url(settings, matches[0])))
    if availability.tmdb_url:
        buttons.append(SupportButton(text="Open TMDB", url=availability.tmdb_url))
    buttons.append(
        SupportButton(text="Search iBOX", url=search_url(settings, availability.title or ""))
    )
    buttons.append(SupportButton(text="Solved", callback_data="support:solved"))
    return tuple(buttons)


def _requested_part_label(intent: SupportIntent) -> str | None:
    parts: list[str] = []
    if intent.season_number is not None:
        parts.append(f"Season {intent.season_number}")
    if intent.episode_number is not None:
        parts.append(f"Episode {intent.episode_number}")
    return " ".join(parts) or None


def _date_text(value: date | None) -> str:
    if value is None:
        return "unknown"
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _format_variant(variants: tuple[str, ...], **values: str) -> str:
    return random.choice(variants).format(**values)
