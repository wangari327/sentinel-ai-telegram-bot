from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.moderation.normalizer import NormalizedMessage

SHORTENER_DOMAINS = {
    "bit.ly",
    "cutt.ly",
    "goo.gl",
    "is.gd",
    "lnkd.in",
    "ow.ly",
    "rebrand.ly",
    "s.id",
    "shorturl.at",
    "t.co",
    "tiny.cc",
    "tinyurl.com",
}
SAFE_DISCUSSION_DOMAINS = {
    "github.com",
    "gitlab.com",
    "youtube.com",
    "youtu.be",
    "wikipedia.org",
    "openai.com",
}
ZERO_WIDTH_MARKERS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
EMOJI_RE = re.compile(
    "[\U0001f300-\U0001f6ff\U0001f700-\U0001f77f\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff\U0001f900-\U0001f9ff\U0001fa00-\U0001faff]"
)


def _deobfuscate(text: str) -> str:
    table = str.maketrans(
        {
            "0": "o",
            "1": "i",
            "3": "e",
            "4": "a",
            "5": "s",
            "7": "t",
            "@": "a",
            "$": "s",
            "!": "i",
            "|": "i",
        }
    )
    text = ZERO_WIDTH_MARKERS.sub("", text.casefold()).translate(table)
    return re.sub(r"[^a-z0-9+]+", " ", text)


def _compact_letters(text: str) -> str:
    return re.sub(r"[^a-z0-9+]+", "", _deobfuscate(text))


@dataclass(frozen=True, slots=True)
class SenderContext:
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    is_admin: bool = False
    is_trusted: bool = False
    recently_joined: bool = False
    recent_message_count: int = 0
    previous_violation_score: float = 0.0


@dataclass(frozen=True, slots=True)
class MessageFeatures:
    contains_url: bool
    contains_tme_link: bool
    contains_bot_start_link: bool
    contains_invite_link: bool
    contains_shortener: bool
    contains_porn_bait: bool
    contains_adult_spam_cta: bool
    contains_urgency_lure: bool
    contains_suspicious_adult_story_lure: bool
    contains_crypto_scam: bool
    contains_fake_reward: bool
    contains_telegram_login_phishing_language: bool
    contains_many_emojis: bool
    contains_obfuscated_text: bool
    contains_zero_width_chars: bool
    repeated_message: bool
    user_recently_joined: bool
    user_high_frequency: bool
    user_previous_violations: bool
    domain_blocked: bool
    domain_allowed: bool
    sender_trusted: bool
    sender_admin: bool
    message_language: str | None
    excessive_mentions: bool
    channel_promo_pattern: bool
    high_risk_link: bool
    risk_signal_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_features(
    normalized: NormalizedMessage,
    *,
    sender: SenderContext | None = None,
    domain_statuses: dict[str, str] | None = None,
    repeated_message: bool = False,
) -> MessageFeatures:
    sender = sender or SenderContext()
    domain_statuses = domain_statuses or {}
    text = normalized.text
    deobfuscated = _deobfuscate(text)
    compact = _compact_letters(text)
    lower = text.casefold()

    contains_tme_link = any(
        "t.me/" in link.lower() or "telegram.me/" in link.lower()
        for link in normalized.telegram_links
    )
    contains_bot_start_link = any(
        re.search(r"(?:t|telegram)\.me/[a-z0-9_]*bot(?:\?|/)?", link, re.IGNORECASE)
        and re.search(r"(?:start|startapp)=", link, re.IGNORECASE)
        for link in normalized.telegram_links
    )
    contains_invite_link = any(
        re.search(r"(?:t|telegram)\.me/(?:joinchat/|\+)", link, re.IGNORECASE)
        for link in normalized.telegram_links
    )
    contains_shortener = any(domain in SHORTENER_DOMAINS for domain in normalized.domains)

    porn_patterns = [
        r"free\s+porn",
        r"leaked?\s+(?:video|pics?)",
        r"18\+",
        r"watch\s+(?:before|b4)\s+(?:deleted|removed|takedown|ban)",
        r"private\s+(?:channel|group).*(?:girls|video|leak)",
        r"(?:hidden\s+cam|private\s+tape|full\s+tape|view\s+full\s+scene|watch\s+uncut)",
        r"(?:hot\s+)?instagram\s+girl.{0,60}(?:exposed|naked|riding|cock)",
        r"(?:got\s+exposed|exposed).{0,60}(?:riding|cock|naked|p\s*ssy|pussy|dick)",
        r"sex\s+video",
    ]
    contains_porn_bait = any(re.search(pattern, deobfuscated) for pattern in porn_patterns)
    contains_porn_bait = contains_porn_bait or any(
        term in compact
        for term in (
            "freeporn",
            "leakedvideo",
            "18+video",
            "watchbeforedeleted",
            "watchbeforetakedown",
            "hiddencam",
            "privatetape",
            "viewfullscene",
            "watchuncut",
            "instagramgirlgotexposed",
            "hotinstagramgirl",
            "ridingcock",
        )
    )

    adult_lure_patterns = [
        r"\b(?:xxx|nsfw|onlyfans)\b",
        r"\b(?:hidden\s+cam|private\s+tape|full\s+tape|uncut\s+video|full\s+scene)\b",
        (
            r"\b(?:leaked?|caught|spotted|banned|deleted|exclusive|live|hidden)\b.{0,60}"
            r"\b(?:naked|p\s*ssy|pussy|dick|cock|f\s*cked|fucked|sex|swallowed|pounded|"
            r"riding|balls\s+deep)\b"
        ),
        (
            r"\b(?:step\s*sis|stepsis|stepmom|coworker|cousin|babysitter|maid|"
            r"roommate|gym\s+girl|instagram\s+girl|hot\s+instagram\s+girl|masseuse|massageuse)\b.{0,90}"
            r"\b(?:naked|xxx|p\s*ssy|pussy|dick|f\s*cked|fucked|swallowed|pounded|"
            r"riding|cock|legs\s+wide|shower|exposed)\b"
        ),
        (
            r"\b(?:naked|p\s*ssy|pussy|dick|cock|f\s*cked|fucked|sex)\b.{0,60}"
            r"\b(?:video|tape|cam|full|watch|unlock|scene)\b"
        ),
        r"\b(?:hot\s+)?instagram\s+girl\b.{0,80}\b(?:got\s+)?exposed\b",
        r"\briding\s+cock\b",
    ]
    adult_lure = any(re.search(pattern, deobfuscated) for pattern in adult_lure_patterns)
    adult_lure = adult_lure or any(
        term in compact
        for term in (
            "xxx",
            "onlyfans",
            "hiddencam",
            "privatetape",
            "fulltape",
            "uncutvideo",
            "fullscene",
            "fcked",
            "pussy",
            "dick",
            "cock",
            "ridingcock",
            "gotexposed",
            "instagramgirl",
            "hotinstagramgirl",
            "stepmom",
            "stepsis",
            "gymgirl",
        )
    )

    cta_patterns = [
        (
            r"\b(?:watch\s+now|see\s+more|view\s+full\s+(?:scene|video)?|"
            r"tap\s+to\s+watch|tap\s+to\s+play|unlock\s+video|click\s+here)\b"
        ),
        r"\b(?:watch|view|unlock|tap|click)\b.{0,35}\b(?:full|video|scene|tape|uncut|here|now)\b",
        r"\bfull\b",
    ]
    cta_count = sum(len(re.findall(pattern, deobfuscated)) for pattern in cta_patterns)
    contains_adult_spam_cta = adult_lure and (cta_count > 0 or contains_bot_start_link)

    urgency_patterns = [
        r"\blink\s+expires\s+in\s+\d+\s*(?:s|sec|secs|seconds|m|min|mins|minutes)\b",
        (
            r"\b(?:watch|view|tap|click)\b.{0,45}\b(?:before|b4)\b.{0,25}"
            r"\b(?:takedown|deleted|removed|ban)\b"
        ),
        r"\bleaked?\s+(?:just\s+)?\d+\s*(?:s|sec|secs|m|min|mins|minutes)\s+ago\b",
        r"\blast\s+chance\s+to\s+watch\b",
        r"\bprivate\s+tape\s+inside\b",
    ]
    contains_urgency_lure = any(re.search(pattern, deobfuscated) for pattern in urgency_patterns)
    contains_urgency_lure = contains_urgency_lure or any(
        term in compact
        for term in (
            "linkexpiresin",
            "watchbeforetakedown",
            "watchbeforedeleted",
            "watchbeforeban",
            "leakedjust",
            "lastchancetowatch",
            "privatetapeinside",
        )
    )
    contains_suspicious_adult_story_lure = adult_lure and (
        contains_adult_spam_cta
        or contains_urgency_lure
        or contains_bot_start_link
        or contains_porn_bait
    )
    contains_porn_bait = contains_porn_bait or contains_suspicious_adult_story_lure

    contains_crypto_scam = any(
        phrase in deobfuscated
        for phrase in (
            "airdrop",
            "connect wallet",
            "claim token",
            "crypto giveaway",
            "double your crypto",
            "wallet verification",
        )
    )
    contains_fake_reward = any(
        phrase in deobfuscated
        for phrase in (
            "free telegram premium",
            "claim reward",
            "free gift",
            "you won",
            "limited reward",
            "nitro giveaway",
        )
    )
    contains_login_phishing = any(
        phrase in deobfuscated
        for phrase in (
            "login to continue",
            "telegram login",
            "verify your account",
            "click bot to verify",
            "scan qr to login",
        )
    )
    emoji_count = len(EMOJI_RE.findall(text))
    contains_many_emojis = emoji_count >= 10
    contains_obfuscated_text = normalized.suspicious_unicode_count > 0 or bool(
        re.search(r"[a-z][._\-* ]{1,3}[a-z][._\-* ]{1,3}[a-z]", lower)
    )
    contains_zero_width_chars = normalized.zero_width_count > 0
    excessive_mentions = len(re.findall(r"@[A-Za-z0-9_]{3,}", text)) >= 5
    channel_promo_pattern = bool(
        re.search(r"\b(join|subscribe|follow)\b.{0,40}\b(channel|group|private)\b", deobfuscated)
    )

    domain_blocked = any(status == "blocked" for status in domain_statuses.values())
    domain_allowed = bool(normalized.domains) and all(
        domain_statuses.get(domain) == "allowed" or domain in SAFE_DISCUSSION_DOMAINS
        for domain in normalized.domains
    )
    user_high_frequency = sender.recent_message_count >= 6
    user_previous_violations = sender.previous_violation_score > 0.0
    high_risk_link = bool(
        domain_blocked
        or contains_bot_start_link
        or contains_invite_link
        or (
            normalized.domains
            and (
                contains_porn_bait
                or contains_adult_spam_cta
                or contains_urgency_lure
                or contains_suspicious_adult_story_lure
                or contains_crypto_scam
                or contains_fake_reward
                or contains_login_phishing
                or contains_shortener
            )
        )
    )

    signals = [
        bool(normalized.urls),
        contains_tme_link,
        contains_bot_start_link,
        contains_invite_link,
        contains_shortener,
        contains_porn_bait,
        contains_adult_spam_cta,
        contains_urgency_lure,
        contains_suspicious_adult_story_lure,
        contains_crypto_scam,
        contains_fake_reward,
        contains_login_phishing,
        contains_many_emojis,
        contains_obfuscated_text,
        contains_zero_width_chars,
        repeated_message,
        sender.recently_joined,
        user_high_frequency,
        user_previous_violations,
        domain_blocked,
        excessive_mentions,
        channel_promo_pattern,
    ]

    return MessageFeatures(
        contains_url=bool(normalized.urls),
        contains_tme_link=contains_tme_link,
        contains_bot_start_link=contains_bot_start_link,
        contains_invite_link=contains_invite_link,
        contains_shortener=contains_shortener,
        contains_porn_bait=contains_porn_bait,
        contains_adult_spam_cta=contains_adult_spam_cta,
        contains_urgency_lure=contains_urgency_lure,
        contains_suspicious_adult_story_lure=contains_suspicious_adult_story_lure,
        contains_crypto_scam=contains_crypto_scam,
        contains_fake_reward=contains_fake_reward,
        contains_telegram_login_phishing_language=contains_login_phishing,
        contains_many_emojis=contains_many_emojis,
        contains_obfuscated_text=contains_obfuscated_text,
        contains_zero_width_chars=contains_zero_width_chars,
        repeated_message=repeated_message,
        user_recently_joined=sender.recently_joined,
        user_high_frequency=user_high_frequency,
        user_previous_violations=user_previous_violations,
        domain_blocked=domain_blocked,
        domain_allowed=domain_allowed,
        sender_trusted=sender.is_trusted,
        sender_admin=sender.is_admin,
        message_language=None,
        excessive_mentions=excessive_mentions,
        channel_promo_pattern=channel_promo_pattern,
        high_risk_link=high_risk_link,
        risk_signal_count=sum(1 for signal in signals if signal),
    )
