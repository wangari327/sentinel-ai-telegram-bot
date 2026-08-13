from app.moderation.feature_extractor import SenderContext, extract_features
from app.moderation.normalizer import normalize_message_parts


def test_porn_bait_obfuscation_detection() -> None:
    normalized = normalize_message_parts(text="fr33 p0rn leaked video https://x.example/a")
    features = extract_features(normalized)

    assert features.contains_porn_bait
    assert features.high_risk_link


def test_blocked_domain_is_flagged() -> None:
    normalized = normalize_message_parts(text="claim now https://bad.example")
    features = extract_features(normalized, domain_statuses={"bad.example": "blocked"})

    assert features.domain_blocked
    assert features.high_risk_link


def test_allowed_domain_is_marked_safe() -> None:
    normalized = normalize_message_parts(text="Patch notes https://github.com/example/project")
    features = extract_features(normalized, domain_statuses={"github.com": "allowed"})

    assert features.domain_allowed
    assert not features.high_risk_link


def test_trusted_sender_context_is_preserved() -> None:
    normalized = normalize_message_parts(text="normal chat")
    features = extract_features(normalized, sender=SenderContext(is_trusted=True))

    assert features.sender_trusted
