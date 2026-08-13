from app.config import load_settings
from app.config_check import _missing


def test_config_check_accepts_hcnsec_vps_config() -> None:
    settings = load_settings(
        {
            "BOT_TOKEN": "token",
            "WEBHOOK_BASE_URL": "https://sentinel.example.com",
            "WEBHOOK_SECRET": "secret",
            "AUTHORIZED_CHAT_IDS": "-100123",
            "AI_PROVIDER": "hcnsec",
            "HCNSEC_API_KEY": "provider-key",
            "HCNSEC_BASE_URL": "https://api.hcnsec.cn",
        }
    )

    assert _missing(settings) == []


def test_config_check_requires_authorized_chat_or_owner() -> None:
    settings = load_settings(
        {
            "BOT_TOKEN": "token",
            "WEBHOOK_BASE_URL": "https://sentinel.example.com",
            "WEBHOOK_SECRET": "secret",
            "AI_PROVIDER": "rules_only",
            "REQUIRE_AUTHORIZED_CHATS": "true",
        }
    )

    assert "AUTHORIZED_CHAT_IDS or OWNER_ADMIN_IDS" in _missing(settings)


def test_config_check_deepseek_requires_deepseek_key() -> None:
    settings = load_settings(
        {
            "BOT_TOKEN": "token",
            "WEBHOOK_BASE_URL": "https://sentinel.example.com",
            "WEBHOOK_SECRET": "secret",
            "AUTHORIZED_CHAT_IDS": "-100123",
            "AI_PROVIDER": "deepseek",
            "HCNSEC_API_KEY": "not-used-for-deepseek",
        }
    )

    assert "DEEPSEEK_API_KEY" in _missing(settings)
