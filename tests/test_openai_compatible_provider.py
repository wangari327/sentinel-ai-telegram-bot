from app.config import load_settings
from app.moderation.ai_classifier import (
    DeepSeekProvider,
    GenericOpenAICompatibleProvider,
    provider_from_name,
)


def test_hcnsec_provider_alias_uses_openai_compatible_config() -> None:
    settings = load_settings(
        {
            "AI_PROVIDER": "hcnsec",
            "HCNSEC_API_KEY": "test-key",
            "HCNSEC_BASE_URL": "https://api.hcnsec.cn",
            "HCNSEC_MODEL": "deepseek-v4-flash",
            "HCNSEC_PROVIDER_NAME": "hcnsec",
        }
    )

    provider = provider_from_name("hcnsec", settings)

    assert isinstance(provider, GenericOpenAICompatibleProvider)
    assert provider.provider_name == "hcnsec"
    assert provider.base_url == "https://api.hcnsec.cn"
    assert provider.model_name == "deepseek-v4-flash"


def test_deepseek_provider_uses_deepseek_key_not_hcnsec_alias() -> None:
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

    provider = provider_from_name("deepseek", settings)

    assert isinstance(provider, DeepSeekProvider)
    assert provider.api_key == "deepseek-key"
    assert provider.base_url == "https://api.deepseek.com"
    assert provider.model_name == "deepseek-chat"
