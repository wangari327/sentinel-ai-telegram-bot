from types import SimpleNamespace

from app.moderation.normalizer import normalize_message_parts, normalize_telegram_message


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


def test_forwarded_story_metadata_is_preserved_for_moderation() -> None:
    message = SimpleNamespace(
        text=None,
        caption=None,
        entities=None,
        caption_entities=None,
        story=SimpleNamespace(chat=SimpleNamespace(title="Wet Dreams"), id=1548),
    )

    normalized = normalize_telegram_message(message)

    assert "forwarded_telegram_story" in normalized.content_flags
    assert "Forwarded Telegram story from Wet Dreams" in normalized.text
