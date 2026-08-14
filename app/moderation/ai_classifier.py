from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.moderation.prompts import OUTPUT_SCHEMA, PROMPT_VERSION, build_classifier_messages

Label = Literal["spam", "suspicious", "not_spam"]
LureType = Literal[
    "porn_bait",
    "phishing",
    "crypto_scam",
    "fake_giveaway",
    "malware",
    "impersonation",
    "spam_channel_promo",
    "suspicious_bot_link",
    "suspicious_invite_link",
    "unknown",
]
RecommendedAction = Literal["delete", "delete_and_ban", "ask_admin", "allow"]


class ClassificationResult(BaseModel):
    label: Label
    confidence: float = Field(ge=0.0, le=1.0)
    risk_reasons: list[str] = Field(default_factory=list)
    safe_reasons: list[str] = Field(default_factory=list)
    detected_lure_type: LureType | None = None
    recommended_action: RecommendedAction
    needs_training_review: bool = False
    provider_name: str = "unknown"
    model_name: str | None = None
    prompt_version: str = PROMPT_VERSION
    raw_response: str | None = None
    error: str | None = None


class ClassificationRequest(BaseModel):
    normalized_text: str
    raw_excerpt: str
    urls: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    telegram_links: list[str] = Field(default_factory=list)
    rule_features: dict[str, Any] = Field(default_factory=dict)
    rule_score: float = 0.0
    sender_context: dict[str, Any] = Field(default_factory=dict)
    group_context: dict[str, Any] = Field(default_factory=dict)
    recent_user_behavior: dict[str, Any] = Field(default_factory=dict)
    relevant_spam_examples: list[str] = Field(default_factory=list)
    relevant_not_spam_examples: list[str] = Field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    requested_output_schema: dict[str, Any] = Field(default_factory=lambda: OUTPUT_SCHEMA)

    def prompt_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"requested_output_schema"})


class AIProvider(ABC):
    provider_name: str = "base"
    model_name: str | None = None

    @abstractmethod
    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        raise NotImplementedError


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("response did not contain a JSON object")
    return text[start : end + 1]


def parse_classification_json(
    raw: str,
    *,
    provider_name: str,
    model_name: str | None,
    prompt_version: str = PROMPT_VERSION,
) -> ClassificationResult:
    data = json.loads(_extract_json_object(raw))
    result = ClassificationResult.model_validate(data)
    result.provider_name = provider_name
    result.model_name = model_name
    result.prompt_version = prompt_version
    result.raw_response = raw
    return result


def conservative_result(
    *,
    label: Label = "suspicious",
    confidence: float = 0.55,
    reasons: list[str] | None = None,
    provider_name: str = "rules_only",
    model_name: str | None = None,
    error: str | None = None,
) -> ClassificationResult:
    action: RecommendedAction = "ask_admin"
    if label == "spam" and confidence >= 0.95:
        action = "delete"
    elif label == "not_spam":
        action = "allow"
    return ClassificationResult(
        label=label,
        confidence=confidence,
        risk_reasons=reasons or [],
        safe_reasons=[],
        detected_lure_type="unknown" if label != "not_spam" else None,
        recommended_action=action,
        needs_training_review=label != "not_spam",
        provider_name=provider_name,
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        error=error,
    )


class RulesOnlyProvider(AIProvider):
    provider_name = "rules_only"
    model_name = "rules"

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        features = request.rule_features
        score = float(request.rule_score)
        reasons: list[str] = []
        lure_type: LureType | None = "unknown"
        if features.get("domain_blocked"):
            score = max(score, 0.97)
            reasons.append("blocked domain")
        if features.get("contains_bot_start_link"):
            reasons.append("suspicious bot start link")
            lure_type = "suspicious_bot_link"
        if features.get("contains_invite_link"):
            reasons.append("suspicious invite link")
            lure_type = "suspicious_invite_link"
        if features.get("contains_porn_bait"):
            reasons.append("porn-bait phrase")
            lure_type = "porn_bait"
        if features.get("contains_adult_spam_cta"):
            reasons.append("adult spam call-to-action")
            lure_type = "porn_bait"
        if features.get("contains_urgency_lure"):
            reasons.append("urgent watch/expiry lure")
            lure_type = "porn_bait"
        if features.get("contains_suspicious_adult_story_lure"):
            reasons.append("adult clickbait story lure")
            lure_type = "porn_bait"
        if features.get("contains_crypto_scam"):
            reasons.append("crypto scam phrase")
            lure_type = "crypto_scam"
        if features.get("contains_fake_reward"):
            reasons.append("fake reward phrase")
            lure_type = "fake_giveaway"
        if features.get("contains_telegram_login_phishing_language"):
            reasons.append("login phishing language")
            lure_type = "phishing"

        severe_adult_lure = bool(
            features.get("contains_suspicious_adult_story_lure")
            and (features.get("contains_adult_spam_cta") or features.get("contains_porn_bait"))
        )
        severe_nonlink_spam = bool(
            severe_adult_lure
            or features.get("contains_crypto_scam")
            or features.get("contains_fake_reward")
            or features.get("contains_telegram_login_phishing_language")
        )

        if score >= 0.96 and (features.get("high_risk_link") or severe_nonlink_spam):
            label: Label = "spam"
            action: RecommendedAction = "delete"
            review = False
        elif score >= 0.72:
            label = "suspicious"
            action = "ask_admin"
            review = True
        elif score <= 0.20:
            label = "not_spam"
            action = "allow"
            review = False
        else:
            label = "suspicious"
            action = "ask_admin"
            review = True

        result_confidence = 1.0 - score if label == "not_spam" else score
        return ClassificationResult(
            label=label,
            confidence=max(0.0, min(1.0, result_confidence)),
            risk_reasons=list(dict.fromkeys(reasons)),
            safe_reasons=[],
            detected_lure_type=lure_type if label != "not_spam" else None,
            recommended_action=action,
            needs_training_review=review,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=PROMPT_VERSION,
        )


class MockProvider(AIProvider):
    provider_name = "mock"
    model_name = "mock"

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        text = request.normalized_text.casefold()
        if any(term in text for term in ("free porn", "leaked video", "connect wallet")):
            return ClassificationResult(
                label="spam",
                confidence=0.93,
                risk_reasons=["mock matched spam lure"],
                safe_reasons=[],
                detected_lure_type="unknown",
                recommended_action="delete",
                needs_training_review=False,
                provider_name=self.provider_name,
                model_name=self.model_name,
            )
        return ClassificationResult(
            label="not_spam",
            confidence=0.85,
            risk_reasons=[],
            safe_reasons=["mock default benign"],
            detected_lure_type=None,
            recommended_action="allow",
            needs_training_review=False,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


class OpenAICompatibleProvider(AIProvider):
    provider_name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout: float,
        max_retries: int,
        use_structured_output: bool,
        provider_name: str,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.use_structured_output = use_structured_output
        self.provider_name = provider_name

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        if not self.api_key and self.provider_name == "openai":
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIProvider")
        messages = build_classifier_messages(request.prompt_payload())
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
        }
        if self.use_structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "telegram_moderation_classification",
                    "strict": True,
                    "schema": OUTPUT_SCHEMA,
                },
            }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    raw = data["choices"][0]["message"]["content"]
                    return parse_classification_json(
                        raw,
                        provider_name=self.provider_name,
                        model_name=self.model_name,
                    )
                except (KeyError, ValueError, ValidationError, httpx.HTTPError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        payload["messages"] = [
                            *messages,
                            {
                                "role": "user",
                                "content": (
                                    "Repair the previous output. Return only a JSON object "
                                    "that exactly matches the schema."
                                ),
                            },
                        ]
                        await asyncio.sleep(0.15 * (attempt + 1))
                        continue
                    break
        raise RuntimeError(f"{self.provider_name} classification failed: {last_error}")


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model_name=settings.openai_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            use_structured_output=settings.ai_use_structured_output,
            provider_name="openai",
        )


class GenericOpenAICompatibleProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_compatible_base_url:
            raise RuntimeError(
                "OPENAI_COMPATIBLE_BASE_URL, NEWAPI_BASE_URL, or HCNSEC_BASE_URL is required"
            )
        if not settings.openai_compatible_api_key:
            raise RuntimeError(
                "OPENAI_COMPATIBLE_API_KEY, NEWAPI_API_KEY, or HCNSEC_API_KEY is required"
            )
        super().__init__(
            api_key=settings.openai_compatible_api_key,
            base_url=settings.openai_compatible_base_url,
            model_name=settings.openai_compatible_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            use_structured_output=settings.openai_compatible_use_structured_output,
            provider_name=settings.openai_compatible_provider_name,
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for DeepSeek")
        super().__init__(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model_name=settings.deepseek_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            use_structured_output=settings.openai_compatible_use_structured_output,
            provider_name=settings.deepseek_provider_name,
        )


class OllamaProvider(OpenAICompatibleProvider):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            api_key="",
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            use_structured_output=False,
            provider_name="ollama",
        )


class GeminiProvider(AIProvider):
    provider_name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.gemini_api_key
        self.model_name = settings.gemini_model
        self.timeout = settings.ai_timeout_seconds
        self.max_retries = settings.ai_max_retries

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is required for GeminiProvider")
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "system": build_classifier_messages(request.prompt_payload())[
                                        0
                                    ]["content"],
                                    "request": request.prompt_payload(),
                                    "schema": OUTPUT_SCHEMA,
                                },
                                ensure_ascii=False,
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model_name}:generateContent?key={self.api_key}"
        )
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    raw = data["candidates"][0]["content"]["parts"][0]["text"]
                    return parse_classification_json(
                        raw,
                        provider_name=self.provider_name,
                        model_name=self.model_name,
                    )
                except (KeyError, ValueError, ValidationError, httpx.HTTPError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.15 * (attempt + 1))
                        continue
        raise RuntimeError(f"Gemini classification failed: {last_error}")


def provider_from_name(name: str, settings: Settings) -> AIProvider:
    normalized = name.lower().strip()
    if normalized == "openai":
        return OpenAIProvider(settings)
    if normalized in {"openai_compatible", "compatible", "newapi", "hcnsec"}:
        return GenericOpenAICompatibleProvider(settings)
    if normalized == "deepseek":
        return DeepSeekProvider(settings)
    if normalized == "gemini":
        return GeminiProvider(settings)
    if normalized == "ollama":
        return OllamaProvider(settings)
    if normalized == "mock":
        return MockProvider()
    if normalized in {"rules", "rules_only", "rules-only"}:
        return RulesOnlyProvider()
    raise ValueError(f"Unknown AI_PROVIDER: {name}")


class ProviderChain(AIProvider):
    provider_name = "provider_chain"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.primary = provider_from_name(settings.ai_provider, settings)
        self.fallback = provider_from_name(settings.ai_fallback_provider, settings)
        self.rules_only = RulesOnlyProvider()

    async def classify(self, request: ClassificationRequest) -> ClassificationResult:
        try:
            return await self.primary.classify(request)
        except (RuntimeError, httpx.HTTPError, ValidationError, ValueError) as exc:
            primary_error = str(exc)
            if self.settings.ai_enable_provider_fallback:
                try:
                    result = await self.fallback.classify(request)
                    result.error = primary_error
                    return result
                except (RuntimeError, httpx.HTTPError, ValidationError, ValueError) as fallback_exc:
                    primary_error = f"{primary_error}; fallback failed: {fallback_exc}"
            result = await self.rules_only.classify(request)
            result.error = primary_error
            return result


def get_ai_provider(settings: Settings) -> AIProvider:
    return ProviderChain(settings)
