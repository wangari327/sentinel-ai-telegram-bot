from app.moderation.normalizer import normalize_message_parts


def test_url_extraction_and_tme_detection() -> None:
    normalized = normalize_message_parts(
        text="Watch https://t.me/+invite and visit https://bit.ly/abc?x=1"
    )

    assert "https://t.me/+invite" in normalized.urls
    assert "bit.ly" in normalized.domains
    assert normalized.telegram_links == ["https://t.me/+invite"]


def test_text_hash_is_stable_after_whitespace_normalization() -> None:
    left = normalize_message_parts(text="hello   world")
    right = normalize_message_parts(text="hello world")

    assert left.text_hash == right.text_hash
