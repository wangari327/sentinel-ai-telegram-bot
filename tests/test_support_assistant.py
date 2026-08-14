from app.config import load_settings
from app.support.assistant import build_support_reply, detect_support_intent
from app.support.ibox_search import IboxItem, item_url, search_url


def test_detects_movie_request() -> None:
    intent = detect_support_intent("Please upload the movie Dune Part Two")

    assert intent is not None
    assert intent.kind == "request"
    assert intent.category_hint == "movie"
    assert intent.title_query == "Dune Part Two"


def test_detects_broken_link_issue() -> None:
    intent = detect_support_intent("The Shogun link is broken, it is not working")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.issue_type == "broken_link"
    assert "Shogun" in (intent.title_query or "")


def test_detects_howto_request() -> None:
    intent = detect_support_intent("How do I download and play the files?")

    assert intent is not None
    assert intent.kind == "howto"


def test_builds_search_reply_for_found_item() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    item = IboxItem(
        id=1,
        title="Shogun",
        episode_title="Season 1",
        category="tv",
        slug="shogun-season-1",
        year=2024,
        rating=8.7,
        download_link="https://example.com",
    )
    intent = detect_support_intent("where can I find Shogun")

    reply = build_support_reply(intent=intent, matches=[item], settings=settings)

    assert reply is not None
    assert "Found this" in reply.text
    assert "https://ibox-tv.com/show/shogun-season-1" in reply.text
    assert item_url(settings, item) == "https://ibox-tv.com/show/shogun-season-1"


def test_without_tvweb_db_request_points_to_search_page() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    intent = detect_support_intent("where can I find Severance")

    reply = build_support_reply(intent=intent, matches=[], settings=settings)

    assert reply is not None
    assert "Search iBOX TV" in reply.text
    assert "https://ibox-tv.com/?search=Severance" in reply.text


def test_search_url_uses_category_domains() -> None:
    settings = load_settings({})

    assert search_url(settings, "naruto", "anime").startswith("https://anime.ibox-tv.com")
    assert search_url(settings, "dune", "movie").startswith("https://movies.ibox-tv.com")
