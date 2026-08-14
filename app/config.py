from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from os import environ

MODES = {"normal", "auto_delete", "silent", "monitor_only", "aggressive"}


def _bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _csv_ints(value: str | None) -> frozenset[int]:
    if not value:
        return frozenset()
    ids: set[int] = set()
    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if item:
            ids.add(int(item))
    return frozenset(ids)


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@dataclass(frozen=True, slots=True)
class Settings:
    project_name: str
    bot_token: str
    database_url: str
    redis_url: str | None
    webhook_base_url: str
    webhook_secret: str
    auto_set_webhook: bool
    auto_migrate: bool
    demo_mode: bool
    log_level: str
    retention_days: int
    default_notify_admin_id: int | None
    owner_admin_ids: frozenset[int]
    authorized_chat_ids: frozenset[int]
    require_authorized_chats: bool
    leave_unauthorized_chats: bool
    default_group_mode: str
    ai_provider: str
    ai_fallback_provider: str
    ai_timeout_seconds: float
    ai_max_retries: int
    ai_use_structured_output: bool
    ai_escalate_on_unsure: bool
    ai_enable_provider_fallback: bool
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_escalation_model: str
    openai_compatible_api_key: str
    openai_compatible_base_url: str
    openai_compatible_model: str
    openai_compatible_provider_name: str
    openai_compatible_use_structured_output: bool
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_provider_name: str
    gemini_api_key: str
    gemini_model: str
    ollama_base_url: str
    ollama_model: str
    spam_delete_threshold: float
    spam_ban_threshold: float
    suspicious_low_threshold: float
    suspicious_high_threshold: float
    ai_scan_all_messages: bool
    ai_scan_links_only: bool
    support_enabled: bool
    support_ai_replies: bool
    support_tone: str
    support_reply_cleanup_seconds: int
    tvweb_database_url: str
    tvweb_site_base_url: str
    tvweb_anime_base_url: str
    tvweb_movies_base_url: str
    tutorial_dump_chat_id: int | None

    @property
    def webhook_path(self) -> str:
        return f"/telegram/webhook/{self.webhook_secret}"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url.rstrip('/')}{self.webhook_path}"

    def chat_is_allowlisted(self, telegram_chat_id: int) -> bool:
        if not self.require_authorized_chats:
            return True
        return telegram_chat_id in self.authorized_chat_ids

    def user_is_owner_admin(self, telegram_user_id: int | None) -> bool:
        if telegram_user_id is None:
            return False
        return telegram_user_id in self.owner_admin_ids


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    source = environ if env is None else env
    default_notify_admin_id = (
        int(source["DEFAULT_NOTIFY_ADMIN_ID"])
        if source.get("DEFAULT_NOTIFY_ADMIN_ID")
        else None
    )
    owner_admin_ids = set(_csv_ints(source.get("OWNER_ADMIN_IDS")))
    if default_notify_admin_id:
        owner_admin_ids.add(default_notify_admin_id)

    mode = source.get("DEFAULT_GROUP_MODE", "monitor_only").strip()
    if mode not in MODES:
        raise ValueError(f"DEFAULT_GROUP_MODE must be one of {sorted(MODES)}")

    return Settings(
        project_name=source.get("PROJECT_NAME", "SentinelAI Telegram Anti-Spam Bot"),
        bot_token=source.get("BOT_TOKEN", ""),
        database_url=normalize_database_url(
            source.get("DATABASE_URL", "sqlite:///./sentinel_ai.db")
        ),
        redis_url=source.get("REDIS_URL") or None,
        webhook_base_url=source.get("WEBHOOK_BASE_URL", ""),
        webhook_secret=source.get("WEBHOOK_SECRET", "dev-secret"),
        auto_set_webhook=_bool(source.get("AUTO_SET_WEBHOOK"), True),
        auto_migrate=_bool(source.get("AUTO_MIGRATE"), True),
        demo_mode=_bool(source.get("DEMO_MODE"), False),
        log_level=source.get("LOG_LEVEL", "INFO"),
        retention_days=_int(source.get("RETENTION_DAYS"), 30),
        default_notify_admin_id=default_notify_admin_id,
        owner_admin_ids=frozenset(owner_admin_ids),
        authorized_chat_ids=_csv_ints(source.get("AUTHORIZED_CHAT_IDS")),
        require_authorized_chats=_bool(source.get("REQUIRE_AUTHORIZED_CHATS"), True),
        leave_unauthorized_chats=_bool(source.get("LEAVE_UNAUTHORIZED_CHATS"), False),
        default_group_mode=mode,
        ai_provider=source.get("AI_PROVIDER", "openai").strip().lower(),
        ai_fallback_provider=source.get("AI_FALLBACK_PROVIDER", "rules_only")
        .strip()
        .lower(),
        ai_timeout_seconds=_float(source.get("AI_TIMEOUT_SECONDS"), 6.0),
        ai_max_retries=_int(source.get("AI_MAX_RETRIES"), 2),
        ai_use_structured_output=_bool(source.get("AI_USE_STRUCTURED_OUTPUT"), True),
        ai_escalate_on_unsure=_bool(source.get("AI_ESCALATE_ON_UNSURE"), True),
        ai_enable_provider_fallback=_bool(
            source.get("AI_ENABLE_PROVIDER_FALLBACK"), True
        ),
        openai_api_key=source.get("OPENAI_API_KEY", ""),
        openai_base_url=source.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=source.get("OPENAI_MODEL", "gpt-5.5-mini"),
        openai_escalation_model=source.get("OPENAI_ESCALATION_MODEL", "gpt-5.5"),
        openai_compatible_api_key=(
            source.get("OPENAI_COMPATIBLE_API_KEY")
            or source.get("NEWAPI_API_KEY")
            or source.get("HCNSEC_API_KEY")
            or source.get("DEEPSEEK_API_KEY")
            or ""
        ),
        openai_compatible_base_url=(
            source.get("OPENAI_COMPATIBLE_BASE_URL")
            or source.get("NEWAPI_BASE_URL")
            or source.get("HCNSEC_BASE_URL")
            or source.get("DEEPSEEK_BASE_URL")
            or ""
        ),
        openai_compatible_model=(
            source.get("OPENAI_COMPATIBLE_MODEL")
            or source.get("NEWAPI_MODEL")
            or source.get("HCNSEC_MODEL")
            or source.get("DEEPSEEK_MODEL")
            or "deepseek-v4-flash"
        ),
        openai_compatible_provider_name=(
            source.get("OPENAI_COMPATIBLE_PROVIDER_NAME")
            or source.get("NEWAPI_PROVIDER_NAME")
            or source.get("HCNSEC_PROVIDER_NAME")
            or source.get("DEEPSEEK_PROVIDER_NAME")
            or "openai_compatible"
        ).strip(),
        openai_compatible_use_structured_output=_bool(
            source.get("OPENAI_COMPATIBLE_USE_STRUCTURED_OUTPUT"), False
        ),
        deepseek_api_key=source.get("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=source.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=source.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        deepseek_provider_name=source.get("DEEPSEEK_PROVIDER_NAME", "deepseek").strip(),
        gemini_api_key=source.get("GEMINI_API_KEY", ""),
        gemini_model=source.get("GEMINI_MODEL", "gemini-2.5-flash"),
        ollama_base_url=source.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        ollama_model=source.get("OLLAMA_MODEL", "qwen2.5:7b-instruct"),
        spam_delete_threshold=_float(source.get("SPAM_DELETE_THRESHOLD"), 0.88),
        spam_ban_threshold=_float(source.get("SPAM_BAN_THRESHOLD"), 0.96),
        suspicious_low_threshold=_float(source.get("SUSPICIOUS_LOW_THRESHOLD"), 0.55),
        suspicious_high_threshold=_float(source.get("SUSPICIOUS_HIGH_THRESHOLD"), 0.87),
        ai_scan_all_messages=_bool(source.get("AI_SCAN_ALL_MESSAGES"), False),
        ai_scan_links_only=_bool(source.get("AI_SCAN_LINKS_ONLY"), True),
        support_enabled=_bool(source.get("SUPPORT_ENABLED"), True),
        support_ai_replies=_bool(source.get("SUPPORT_AI_REPLIES"), True),
        support_tone=source.get(
            "SUPPORT_TONE",
            "playful, lightly sarcastic, chatty, funny, helpful, and never rude",
        ),
        support_reply_cleanup_seconds=_int(source.get("SUPPORT_REPLY_CLEANUP_SECONDS"), 180),
        tvweb_database_url=normalize_database_url(source.get("TVWEB_DATABASE_URL", "")),
        tvweb_site_base_url=source.get("TVWEB_SITE_BASE_URL", "https://ibox-tv.com"),
        tvweb_anime_base_url=source.get("TVWEB_ANIME_BASE_URL", "https://anime.ibox-tv.com"),
        tvweb_movies_base_url=source.get("TVWEB_MOVIES_BASE_URL", "https://movies.ibox-tv.com"),
        tutorial_dump_chat_id=_optional_int(source.get("TUTORIAL_DUMP_CHAT_ID")),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


settings = get_settings()
