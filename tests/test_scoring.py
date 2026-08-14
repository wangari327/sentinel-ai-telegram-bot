from types import SimpleNamespace

from app.moderation.ai_classifier import ClassificationResult
from app.moderation.feature_extractor import SenderContext, extract_features
from app.moderation.normalizer import normalize_message_parts
from app.moderation.pipeline import should_call_ai
from app.moderation.rules import compute_rule_score
from app.moderation.scoring import ScoreBreakdown, combine_scores, decide_action


def _spam_result(confidence: float = 0.97) -> ClassificationResult:
    return ClassificationResult(
        label="spam",
        confidence=confidence,
        risk_reasons=["test spam"],
        safe_reasons=[],
        detected_lure_type="phishing",
        recommended_action="delete_and_ban",
        provider_name="mock",
    )


def test_threshold_decision_delete_and_ban() -> None:
    normalized = normalize_message_parts(text="login to continue https://t.me/scambot?start=x")
    features = extract_features(normalized)
    rule_score = compute_rule_score(features)
    score = combine_scores(rule_score=rule_score, ai_result=_spam_result(), features=features)

    decision = decide_action(
        score=score,
        ai_result=_spam_result(),
        features=features,
        settings={"mode": "normal", "ban_enabled": True},
        setup_completed=True,
    )

    assert decision.action == "delete_and_ban"
    assert decision.delete
    assert decision.ban


def test_setup_incomplete_forces_monitoring() -> None:
    normalized = normalize_message_parts(text="free porn https://bad.example")
    features = extract_features(normalized)
    rule_score = compute_rule_score(features)
    score = combine_scores(rule_score=rule_score, ai_result=_spam_result(), features=features)

    decision = decide_action(
        score=score,
        ai_result=_spam_result(),
        features=features,
        settings={"mode": "normal", "ban_enabled": True},
        setup_completed=False,
    )

    assert decision.action == "monitor_setup_required"
    assert not decision.delete
    assert not decision.ban


def test_monitor_only_reports_without_deleting() -> None:
    normalized = normalize_message_parts(
        text=(
            "HIDDEN: GYM GIRL walked out of the shower - I f*cked her brains out. "
            "Link expires in 60s - Tap to Watch https://t.me/ojetexxx_bot?startapp=1436"
        )
    )
    features = extract_features(normalized)

    decision = decide_action(
        score=ScoreBreakdown(final_score=0.98, reasons=["adult clickbait"], safe_reasons=[]),
        ai_result=_spam_result(),
        features=features,
        settings={"mode": "monitor_only", "ban_enabled": True},
        setup_completed=True,
    )

    assert decision.action == "monitor"
    assert decision.notify_admin
    assert decision.pending_review
    assert not decision.delete
    assert not decision.ban


async def test_rules_only_deletes_obvious_adult_lure_without_url() -> None:
    from app.moderation.ai_classifier import ClassificationRequest, RulesOnlyProvider

    normalized = normalize_message_parts(
        text=(
            "DELETED: COUSIN spread her legs wide - I destroyed her pussy. "
            "Hidden cam footage - Tap to Watch. WATCH NOW. FULL. WATCH NOW."
        )
    )
    features = extract_features(normalized)
    rule_score = compute_rule_score(features)
    ai_result = await RulesOnlyProvider().classify(
        ClassificationRequest(
            normalized_text=normalized.text,
            raw_excerpt=normalized.raw_excerpt,
            rule_features=features.to_dict(),
            rule_score=rule_score.score,
        )
    )
    score = combine_scores(rule_score=rule_score, ai_result=ai_result, features=features)

    decision = decide_action(
        score=score,
        ai_result=ai_result,
        features=features,
        settings={"mode": "normal", "ban_enabled": True},
        setup_completed=True,
    )

    assert ai_result.label == "spam"
    assert score.final_score >= 0.88
    assert decision.action == "delete"
    assert decision.delete


def test_link_only_ai_gate_still_escalates_risky_text_without_url() -> None:
    normalized = normalize_message_parts(
        text="WATCH NOW: leaked private tape, link expires in 60s, full scene"
    )
    features = extract_features(normalized)

    assert should_call_ai(
        features=features,
        group_settings=SimpleNamespace(ai_scan_all_messages=False, ai_scan_links_only=True),
    )


def test_trusted_user_skip_behavior() -> None:
    from app.moderation.pipeline import should_skip

    normalized = normalize_message_parts(text="hello team")
    sender = SenderContext(is_trusted=True)

    assert should_skip(normalized=normalized, sender=sender, scan_admins=False)
