from app.config import load_settings
from app.support.intent_ai import _intent_from_data


def test_ai_intent_accepts_fuzzy_title_request() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "request",
            "confidence": 0.86,
            "title_query": "godzilla minus one",
            "category_hint": "movie",
            "issue_type": None,
        },
        settings=settings,
    )

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "godzilla minus one"
    assert intent.category_hint == "movie"


def test_ai_intent_accepts_fuzzy_expired_link_issue() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "issue",
            "confidence": 0.92,
            "title_query": "lioness",
            "category_hint": "tv",
            "issue_type": "broken_link",
        },
        settings=settings,
    )

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.title_query == "lioness"
    assert intent.issue_type == "broken_link"


def test_ai_intent_accepts_howto_without_title() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "howto",
            "confidence": 0.81,
            "title_query": None,
            "category_hint": None,
            "issue_type": None,
        },
        settings=settings,
    )

    assert intent is not None
    assert intent.kind == "howto"


def test_ai_intent_rejects_low_confidence() -> None:
    settings = load_settings({"SUPPORT_AI_INTENT_THRESHOLD": "0.8"})

    intent = _intent_from_data(
        {
            "kind": "request",
            "confidence": 0.6,
            "title_query": "Avatar",
            "category_hint": "movie",
            "issue_type": None,
        },
        settings=settings,
    )

    assert intent is None
