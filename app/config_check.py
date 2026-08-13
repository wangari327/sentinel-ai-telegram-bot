from __future__ import annotations

import sys

from app.config import Settings, load_settings


def _missing(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.bot_token:
        missing.append("BOT_TOKEN")
    if not settings.webhook_base_url:
        missing.append("WEBHOOK_BASE_URL")
    if not settings.webhook_secret or settings.webhook_secret == "dev-secret":
        missing.append("WEBHOOK_SECRET")
    if settings.require_authorized_chats and not (
        settings.authorized_chat_ids or settings.owner_admin_ids
    ):
        missing.append("AUTHORIZED_CHAT_IDS or OWNER_ADMIN_IDS")

    if settings.ai_provider == "openai" and not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if settings.ai_provider in {"openai_compatible", "compatible", "newapi", "hcnsec"}:
        if not settings.openai_compatible_api_key:
            missing.append("OPENAI_COMPATIBLE_API_KEY or HCNSEC_API_KEY")
        if not settings.openai_compatible_base_url:
            missing.append("OPENAI_COMPATIBLE_BASE_URL or HCNSEC_BASE_URL")
    if settings.ai_provider == "deepseek" and not settings.deepseek_api_key:
        missing.append("DEEPSEEK_API_KEY")
    if settings.ai_provider == "gemini" and not settings.gemini_api_key:
        missing.append("GEMINI_API_KEY")
    return missing


def main() -> int:
    settings = load_settings()
    missing = _missing(settings)
    if missing:
        print("Missing required config:")
        for name in missing:
            print(f"- {name}")
        return 1

    print("SentinelAI config looks ready.")
    print(f"AI_PROVIDER={settings.ai_provider}")
    print(f"WEBHOOK_URL={settings.webhook_url}")
    print(f"AUTHORIZED_CHAT_COUNT={len(settings.authorized_chat_ids)}")
    print(f"OWNER_ADMIN_COUNT={len(settings.owner_admin_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
