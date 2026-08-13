from app.config import load_settings
from app.moderation.ai_classifier import GenericOpenAICompatibleProvider, provider_from_name


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
