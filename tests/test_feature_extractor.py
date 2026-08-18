from app.moderation.feature_extractor import SenderContext, extract_features
from app.moderation.normalizer import normalize_message_parts


def test_porn_bait_obfuscation_detection() -> None:
    normalized = normalize_message_parts(text="fr33 p0rn leaked video https://x.example/a")
    features = extract_features(normalized)

    assert features.contains_porn_bait
    assert features.high_risk_link


def test_current_adult_bot_campaign_is_high_risk() -> None:
    normalized = normalize_message_parts(
        caption=(
            "The shy maid is taking xXx red heart down " "https://t.me/ojetexxx_bot?startapp=1436"
        )
    )
    features = extract_features(normalized)

    assert features.contains_bot_start_link
    assert features.contains_porn_bait
    assert features.contains_adult_spam_cta
    assert features.contains_suspicious_adult_story_lure
    assert features.high_risk_link


def test_current_forwarded_story_caption_campaign_is_high_risk() -> None:
    normalized = normalize_message_parts(
        caption="Watch HOT xXXx Here https://t.me/yofurswetzdreabot?startapp=1548"
    )
    features = extract_features(normalized)

    assert features.contains_bot_start_link
    assert features.contains_porn_bait
    assert features.contains_adult_spam_cta
    assert features.contains_suspicious_adult_story_lure
    assert features.high_risk_link


def test_adult_source_forwarded_story_is_high_risk_even_when_caption_hidden() -> None:
    normalized = normalize_message_parts(
        metadata_text="Forwarded Telegram story from Wet Dreams",
        content_flags=["forwarded_telegram_story"],
    )
    features = extract_features(normalized)

    assert features.contains_forwarded_story
    assert features.contains_porn_bait
    assert features.contains_suspicious_adult_story_lure
    assert features.high_risk_link


def test_link_expiry_adult_lure_is_high_risk() -> None:
    normalized = normalize_message_parts(
        text=(
            "HIDDEN: GYM GIRL walked out of the shower - I f*cked her brains out. "
            "Link expires in 60s - Tap to Watch https://t.me/ojetexxx_bot?startapp=1436"
        )
    )
    features = extract_features(normalized)

    assert features.contains_urgency_lure
    assert features.contains_adult_spam_cta
    assert features.contains_suspicious_adult_story_lure
    assert features.high_risk_link


def test_short_harmless_reply_is_not_adult_spam() -> None:
    for text in ("This is good", "Www"):
        normalized = normalize_message_parts(text=text)
        features = extract_features(normalized)

        assert not features.contains_porn_bait
        assert not features.contains_adult_spam_cta
        assert not features.contains_suspicious_adult_story_lure
        assert not features.high_risk_link


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
