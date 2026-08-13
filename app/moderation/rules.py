from __future__ import annotations

from dataclasses import dataclass

from app.moderation.feature_extractor import MessageFeatures


@dataclass(frozen=True, slots=True)
class RuleScore:
    score: float
    reasons: list[str]
    safe_reasons: list[str]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def compute_rule_score(features: MessageFeatures) -> RuleScore:
    score = 0.0
    reasons: list[str] = []
    safe_reasons: list[str] = []

    weights = {
        "domain_blocked": (0.86, "blocked domain"),
        "contains_bot_start_link": (0.42, "Telegram bot start link"),
        "contains_invite_link": (0.34, "Telegram invite link"),
        "contains_shortener": (0.22, "shortened URL"),
        "contains_porn_bait": (0.44, "porn-bait wording"),
        "contains_crypto_scam": (0.40, "crypto scam wording"),
        "contains_fake_reward": (0.34, "fake reward wording"),
        "contains_telegram_login_phishing_language": (0.46, "login phishing wording"),
        "contains_zero_width_chars": (0.18, "zero-width characters"),
        "contains_obfuscated_text": (0.14, "obfuscated text"),
        "contains_many_emojis": (0.10, "many emojis"),
        "excessive_mentions": (0.12, "excessive mentions"),
        "channel_promo_pattern": (0.18, "channel promotion pattern"),
        "repeated_message": (0.22, "repeated message"),
        "user_recently_joined": (0.10, "recently joined sender"),
        "user_high_frequency": (0.12, "high message frequency"),
        "user_previous_violations": (0.18, "previous violations"),
    }
    for field, (weight, reason) in weights.items():
        if getattr(features, field):
            score += weight
            reasons.append(reason)

    if features.contains_url and features.risk_signal_count == 1:
        score += 0.06
        reasons.append("contains URL")

    if features.domain_allowed:
        score -= 0.35
        safe_reasons.append("all linked domains are allowed or commonly safe")

    if features.sender_admin:
        score -= 0.30
        safe_reasons.append("sender is a group admin")

    if features.sender_trusted and not features.high_risk_link:
        score -= 0.55
        safe_reasons.append("sender is trusted")
    elif features.sender_trusted and features.high_risk_link:
        score -= 0.12
        safe_reasons.append("sender is trusted but message has high-risk indicators")

    if features.high_risk_link and score < 0.72:
        score = max(score, 0.72)
        reasons.append("high-risk link pattern")

    return RuleScore(score=clamp(score), reasons=reasons, safe_reasons=safe_reasons)
