import pytest

from app.config import load_settings
from app.moderation.ai_classifier import (
    ClassificationRequest,
    ProviderChain,
    parse_classification_json,
)


def test_ai_json_parsing_valid_response() -> None:
    result = parse_classification_json(
        """
        {"label":"spam","confidence":0.91,"risk_reasons":["bad link"],
        "safe_reasons":[],"detected_lure_type":"phishing",
        "recommended_action":"delete","needs_training_review":false}
        """,
        provider_name="openai",
        model_name="test",
    )

    assert result.label == "spam"
    assert result.confidence == 0.91


def test_ai_json_parsing_invalid_response_fails() -> None:
    with pytest.raises(ValueError):
        parse_classification_json("not json", provider_name="openai", model_name="test")


async def test_provider_chain_falls_back_to_rules_only_without_openai_key() -> None:
    settings = load_settings(
        {
            "AI_PROVIDER": "openai",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "AI_ENABLE_PROVIDER_FALLBACK": "true",
            "OPENAI_API_KEY": "",
        }
    )
    chain = ProviderChain(settings)
    request = ClassificationRequest(
        normalized_text="login to continue https://t.me/scambot?start=x",
        raw_excerpt="login to continue https://t.me/scambot?start=x",
        telegram_links=["https://t.me/scambot?start=x"],
        rule_features={
            "contains_bot_start_link": True,
            "contains_telegram_login_phishing_language": True,
            "high_risk_link": True,
        },
        rule_score=0.98,
    )

    result = await chain.classify(request)

    assert result.provider_name == "rules_only"
    assert result.label == "spam"
    assert result.error


def test_gemini_and_ollama_mock_response_validation() -> None:
    for provider in ("gemini", "ollama"):
        result = parse_classification_json(
            """
            {"label":"suspicious","confidence":0.67,"risk_reasons":["invite link"],
            "safe_reasons":[],"detected_lure_type":"suspicious_invite_link",
            "recommended_action":"ask_admin","needs_training_review":true}
            """,
            provider_name=provider,
            model_name="mock-response",
        )
        assert result.provider_name == provider
        assert result.recommended_action == "ask_admin"
