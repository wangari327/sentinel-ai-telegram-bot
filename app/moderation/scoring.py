from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.moderation.ai_classifier import ClassificationResult
from app.moderation.feature_extractor import MessageFeatures
from app.moderation.rules import RuleScore, clamp


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    final_score: float
    reasons: list[str]
    safe_reasons: list[str]
    spam_similarity: float = 0.0
    not_spam_similarity: float = 0.0


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    notify_admin: bool
    delete: bool
    ban: bool
    pending_review: bool
    reason: str


def combine_scores(
    *,
    rule_score: RuleScore,
    ai_result: ClassificationResult,
    features: MessageFeatures,
    spam_similarity: float = 0.0,
    not_spam_similarity: float = 0.0,
    sender_violation_score: float = 0.0,
) -> ScoreBreakdown:
    ai_component = ai_result.confidence
    if ai_result.label == "not_spam":
        ai_component = 1.0 - ai_result.confidence
    elif ai_result.label == "suspicious":
        ai_component *= 0.78

    score = (
        rule_score.score * 0.42
        + ai_component * 0.40
        + spam_similarity * 0.12
        + sender_violation_score * 0.06
    )
    score -= not_spam_similarity * 0.22

    if features.domain_blocked:
        score = max(score, 0.94)
    if features.high_risk_link and ai_result.label == "spam":
        score = max(score, min(1.0, ai_result.confidence + 0.04))
    if (
        features.contains_suspicious_adult_story_lure
        and features.contains_adult_spam_cta
        and ai_result.label == "spam"
    ):
        score = max(score, 0.90)
    if features.sender_trusted and not features.high_risk_link:
        score = min(score, 0.42)
    if features.sender_admin:
        score = min(score, 0.45)

    reasons = [*rule_score.reasons, *ai_result.risk_reasons]
    safe_reasons = [*rule_score.safe_reasons, *ai_result.safe_reasons]
    return ScoreBreakdown(
        final_score=clamp(score),
        reasons=list(dict.fromkeys(reasons)),
        safe_reasons=list(dict.fromkeys(safe_reasons)),
        spam_similarity=spam_similarity,
        not_spam_similarity=not_spam_similarity,
    )


def _setting(settings: Any, name: str, default: Any) -> Any:
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def decide_action(
    *,
    score: ScoreBreakdown,
    ai_result: ClassificationResult,
    features: MessageFeatures,
    settings: Any,
    setup_completed: bool,
    demo_mode: bool = False,
) -> Decision:
    mode = _setting(settings, "mode", "monitor_only")
    delete_threshold = float(_setting(settings, "spam_delete_threshold", 0.88))
    ban_threshold = float(_setting(settings, "spam_ban_threshold", 0.96))
    suspicious_low = float(_setting(settings, "suspicious_low_threshold", 0.55))
    suspicious_high = float(_setting(settings, "suspicious_high_threshold", 0.87))
    ban_enabled = bool(_setting(settings, "ban_enabled", False))
    silent_enabled = bool(_setting(settings, "silent_enabled", False)) or mode == "silent"

    if not setup_completed:
        return Decision(
            action="monitor_setup_required",
            notify_admin=not silent_enabled,
            delete=False,
            ban=False,
            pending_review=score.final_score >= suspicious_low,
            reason="setup is not completed",
        )

    if mode == "monitor_only" or demo_mode:
        return Decision(
            action="monitor",
            notify_admin=score.final_score >= suspicious_low and not silent_enabled,
            delete=False,
            ban=False,
            pending_review=score.final_score >= suspicious_low,
            reason="monitor-only or demo mode",
        )

    if (
        score.final_score >= ban_threshold
        and features.high_risk_link
        and ban_enabled
        and ai_result.label == "spam"
    ):
        return Decision(
            action="delete_and_ban",
            notify_admin=not silent_enabled,
            delete=True,
            ban=True,
            pending_review=False,
            reason="score exceeded ban threshold with high-risk link",
        )

    if score.final_score >= delete_threshold and ai_result.label in {"spam", "suspicious"}:
        return Decision(
            action="delete",
            notify_admin=not silent_enabled,
            delete=True,
            ban=False,
            pending_review=False,
            reason="score exceeded delete threshold",
        )

    if mode == "aggressive" and score.final_score >= suspicious_high:
        return Decision(
            action="delete_pending_review",
            notify_admin=not silent_enabled,
            delete=True,
            ban=False,
            pending_review=True,
            reason="aggressive mode temporarily deletes suspicious content",
        )

    if score.final_score >= suspicious_low:
        return Decision(
            action="ask_admin",
            notify_admin=not silent_enabled,
            delete=False,
            ban=False,
            pending_review=True,
            reason="borderline suspicious content",
        )

    return Decision(
        action="allow",
        notify_admin=False,
        delete=False,
        ban=False,
        pending_review=False,
        reason="below suspicious threshold",
    )
