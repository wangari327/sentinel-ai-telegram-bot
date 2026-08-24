from app.config import load_settings
from app.support.intent_ai import _intent_from_data, _merge_candidate_from_data


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


def test_ai_intent_preserves_season_episode_numbers() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "issue",
            "confidence": 0.92,
            "title_query": "Silo",
            "category_hint": "tv",
            "issue_type": "missing_episode",
            "season_number": 3,
            "episode_number": 8,
        },
        settings=settings,
    )

    assert intent is not None
    assert intent.season_number == 3
    assert intent.episode_number == 8


def test_ai_intent_preserves_season_range() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "request",
            "confidence": 0.92,
            "title_query": "Merlin",
            "category_hint": "tv",
            "season_number": 1,
            "season_end_number": 5,
        },
        settings=settings,
    )

    assert intent is not None
    assert intent.season_number == 1
    assert intent.season_end_number == 5


def test_ai_intent_rejects_generic_search_engine_request() -> None:
    settings = load_settings({})

    intent = _intent_from_data(
        {
            "kind": "request",
            "confidence": 0.92,
            "title_query": "Search engines",
            "category_hint": None,
        },
        settings=settings,
    )

    assert intent is None


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


def test_ai_merge_candidate_accepts_known_candidate_id() -> None:
    settings = load_settings({})

    candidate_id = _merge_candidate_from_data(
        {"candidate_id": 42, "confidence": 0.88, "reason": "same title"},
        candidates=[{"id": 42, "title": "Lioness"}],
        settings=settings,
    )

    assert candidate_id == 42


def test_ai_merge_candidate_rejects_unknown_candidate_id() -> None:
    settings = load_settings({})

    candidate_id = _merge_candidate_from_data(
        {"candidate_id": 99, "confidence": 0.88, "reason": "same title"},
        candidates=[{"id": 42, "title": "Lioness"}],
        settings=settings,
    )

    assert candidate_id is None
