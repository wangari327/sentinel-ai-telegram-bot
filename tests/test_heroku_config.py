import json
from pathlib import Path

from app.config import load_settings, normalize_database_url


def test_heroku_postgres_url_is_normalized() -> None:
    assert normalize_database_url("postgres://user:pass@host/db").startswith(
        "postgresql+psycopg://"
    )


def test_heroku_env_config_loading() -> None:
    settings = load_settings(
        {
            "BOT_TOKEN": "token",
            "WEBHOOK_BASE_URL": "https://example.herokuapp.com",
            "WEBHOOK_SECRET": "secret",
            "AUTHORIZED_CHAT_IDS": "-100123",
            "OWNER_ADMIN_IDS": "42",
            "AI_PROVIDER": "mock",
        }
    )

    assert settings.webhook_url == "https://example.herokuapp.com/telegram/webhook/secret"
    assert -100123 in settings.authorized_chat_ids
    assert 42 in settings.owner_admin_ids


def test_openai_compatible_alias_config_loading() -> None:
    settings = load_settings(
        {
            "AI_PROVIDER": "hcnsec",
            "HCNSEC_API_KEY": "test-key",
            "HCNSEC_BASE_URL": "https://api.hcnsec.cn",
            "HCNSEC_MODEL": "deepseek-v4-flash",
            "HCNSEC_PROVIDER_NAME": "hcnsec",
        }
    )

    assert settings.ai_provider == "hcnsec"
    assert settings.openai_compatible_api_key == "test-key"
    assert settings.openai_compatible_base_url == "https://api.hcnsec.cn"
    assert settings.openai_compatible_model == "deepseek-v4-flash"
    assert settings.openai_compatible_provider_name == "hcnsec"


def test_deepseek_config_uses_deepseek_specific_values() -> None:
    settings = load_settings(
        {
            "AI_PROVIDER": "deepseek",
            "HCNSEC_API_KEY": "hcn-key",
            "HCNSEC_BASE_URL": "https://api.hcnsec.cn",
            "DEEPSEEK_API_KEY": "deepseek-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-chat",
        }
    )

    assert settings.openai_compatible_api_key == "hcn-key"
    assert settings.deepseek_api_key == "deepseek-key"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.deepseek_model == "deepseek-chat"


def test_tvweb_cache_config_defaults() -> None:
    settings = load_settings({})

    assert settings.tvweb_cache_enabled
    assert not settings.tvweb_cache_refresh_on_startup
    assert settings.tvweb_cache_refresh_interval_minutes == 360
    assert settings.tvweb_cache_refresh_times == ()
    assert settings.tvweb_cache_refresh_limit == 5000


def test_app_json_is_valid_heroku_button_json() -> None:
    data = json.loads(Path("app.json").read_text(encoding="utf-8"))

    assert data["name"] == "SentinelAI Telegram Anti-Spam Bot"
    assert "BOT_TOKEN" in data["env"]
    assert "AUTHORIZED_CHAT_IDS" in data["env"]
