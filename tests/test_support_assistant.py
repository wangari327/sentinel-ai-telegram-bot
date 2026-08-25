from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db.models import Base, TvwebCatalogItem
from app.support.assistant import (
    SupportIntent,
    SupportReply,
    availability_blocks_logging,
    build_availability_reply,
    build_support_reply,
    detect_support_intent,
    extract_season_episode_numbers,
    filter_matches_for_requested_part,
    title_query_with_requested_part,
)
from app.support.ibox_search import IboxItem, item_url, search_tvweb_cache, search_url
from app.support.responder import render_support_reply, select_support_chat_config
from app.support.tmdb import TmdbAvailability


def test_detects_movie_request() -> None:
    intent = detect_support_intent("Please upload the movie Dune Part Two")

    assert intent is not None
    assert intent.kind == "request"
    assert intent.category_hint == "movie"
    assert intent.title_query == "Dune Part Two"


def test_detects_requesting_prefix_cleanly() -> None:
    intent = detect_support_intent("requesting AVatar")

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "AVatar"


def test_bare_title_detection_is_opt_in() -> None:
    assert detect_support_intent("Avatar") is None
    assert detect_support_intent("Www", allow_bare_title=True) is None
    assert detect_support_intent("Season 1", allow_bare_title=True).kind == "clarify"

    intent = detect_support_intent("Avatar", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "bare_title"
    assert intent.title_query == "Avatar"


def test_season_only_message_asks_for_clarification() -> None:
    intent = detect_support_intent(
        "Season 1",
        allow_bare_title=True,
        context_title="The Walking Dead: Dead City",
    )

    assert intent is not None
    assert intent.kind == "clarify"
    assert intent.context_title == "The Walking Dead: Dead City"


def test_bare_title_with_season_is_request_with_clean_title() -> None:
    intent = detect_support_intent("Silo season 4", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "Silo"
    assert intent.category_hint == "tv"
    assert intent.season_number == 4


def test_title_with_season_range_keeps_clean_title_and_range() -> None:
    intent = detect_support_intent("Merlin season 1-5 please", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "Merlin"
    assert intent.season_number == 1
    assert intent.season_end_number == 5
    assert title_query_with_requested_part(intent) == "Merlin Season 1-5"


def test_bare_title_with_media_hint_strips_hint_and_requests() -> None:
    intent = detect_support_intent("ER Series", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "ER"
    assert intent.category_hint == "tv"


def test_bare_title_with_year_is_treated_as_request() -> None:
    intent = detect_support_intent("scam 2004", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "scam 2004"


def test_bare_title_with_polite_suffix_is_clean_request() -> None:
    intent = detect_support_intent("grays anatomy plz", allow_bare_title=True)

    assert intent is not None
    assert intent.kind == "request"
    assert intent.title_query == "grays anatomy"


def test_builds_clarification_reply_with_context_button() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    intent = detect_support_intent(
        "Season 1",
        allow_bare_title=True,
        context_title="The Walking Dead: Dead City",
    )

    reply = build_support_reply(intent=intent, matches=[], settings=settings)

    assert reply is not None
    assert "Do you mean" in reply.text
    assert "The Walking Dead" in reply.text
    assert not reply.allow_ai_rewrite
    assert any(button.text == "Search that" for button in reply.buttons)


def test_detects_broken_link_issue() -> None:
    intent = detect_support_intent("The Shogun link is broken, it is not working")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.issue_type == "broken_link"
    assert "Shogun" in (intent.title_query or "")


def test_detects_expired_link_issue_from_group_language() -> None:
    intent = detect_support_intent("Hi\nLink lioness is expired\nPlease fix\nThanks")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.issue_type == "broken_link"
    assert intent.title_query == "lioness"


def test_issue_title_strips_season_episode_noise() -> None:
    intent = detect_support_intent("Fix Silo season 3 episode 1-2")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.title_query == "Silo"
    assert intent.season_number == 3
    assert intent.episode_number == 1


def test_missing_episode_title_query_keeps_title_only() -> None:
    intent = detect_support_intent("Missing episode 8 Silo season 3")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.issue_type == "missing_episode"
    assert intent.title_query == "Silo"
    assert intent.season_number == 3
    assert intent.episode_number == 8


def test_extracts_compact_season_episode_notation() -> None:
    assert extract_season_episode_numbers("S03E08") == (3, 8)
    assert extract_season_episode_numbers("s3 e8") == (3, 8)


def test_detects_howto_request() -> None:
    intent = detect_support_intent("How do I download and play the files?")

    assert intent is not None
    assert intent.kind == "howto"


def test_category_question_is_howto_not_request() -> None:
    intent = detect_support_intent("Pls do u have reality shows")

    assert intent is not None
    assert intent.kind == "howto"
    assert intent.title_query == "reality shows"
    assert intent.category_hint == "tv"


def test_typo_web_series_link_question_is_howto() -> None:
    intent = detect_support_intent("I can get link of it web ser6")

    assert intent is not None
    assert intent.kind == "howto"
    assert intent.title_query == "web series"
    assert intent.category_hint == "tv"


def test_category_howto_reply_does_not_log_request_language() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    intent = detect_support_intent("Pls do u have reality shows")

    reply = build_support_reply(intent=intent, matches=[], settings=settings)

    assert reply is not None
    assert "request pile" not in reply.text
    assert "Search ibox-tv.com" in reply.text
    assert any(button.text == "Search ibox-tv.com" for button in reply.buttons)


def test_support_parser_avoids_substring_false_positives() -> None:
    assert detect_support_intent("The address is fine") is None
    assert detect_support_intent("That soundtrack is nice") is None


def test_support_parser_rejects_generic_help_as_content_request() -> None:
    assert detect_support_intent("send help") is None
    assert detect_support_intent("Search engines", allow_bare_title=True) is None
    assert detect_support_intent("search engines") is None


def test_playback_issue_extracts_title_after_subtitle_words() -> None:
    intent = detect_support_intent("Need subtitles for Silo")

    assert intent is not None
    assert intent.kind == "issue"
    assert intent.issue_type == "playback"
    assert intent.title_query == "Silo"


def test_issue_reply_uses_human_label_not_internal_slug() -> None:
    settings = load_settings({})
    intent = detect_support_intent("Fix Lioness")

    reply = build_support_reply(
        intent=intent,
        matches=[],
        settings=settings,
        occurrence_count=2,
    )

    assert reply is not None
    assert "broken_link" not in reply.text
    assert "link problem" in reply.text
    assert "2" in reply.text


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
    assert "Found on ibox-tv.com" in reply.text
    assert "https://ibox-tv.com/show/shogun-season-1" in reply.text
    assert any(button.url == "https://ibox-tv.com/show/shogun-season-1" for button in reply.buttons)
    assert item_url(settings, item) == "https://ibox-tv.com/show/shogun-season-1"


def test_requested_episode_filter_understands_ranges() -> None:
    item = IboxItem(
        id=1,
        title="Silo",
        episode_title="Season 3 Episode 1-7",
        category="tv",
        slug="silo-season-3-episode-1-7",
        year=2026,
        rating=8.0,
        download_link=None,
    )

    matching = SupportIntent(
        kind="request",
        title_query="Silo",
        category_hint="tv",
        season_number=3,
        episode_number=4,
    )
    missing = SupportIntent(
        kind="request",
        title_query="Silo",
        category_hint="tv",
        season_number=3,
        episode_number=8,
    )

    assert filter_matches_for_requested_part([item], matching) == [item]
    assert filter_matches_for_requested_part([item], missing) == []


def test_requested_season_filter_understands_catalog_ranges() -> None:
    item = IboxItem(
        id=1,
        title="Merlin",
        episode_title="Season 1-5 Complete",
        category="tv",
        slug="merlin-season-1-5-complete",
        year=2008,
        rating=8.0,
        download_link=None,
    )

    matching = SupportIntent(
        kind="request",
        title_query="Merlin",
        category_hint="tv",
        season_number=4,
    )
    missing = SupportIntent(
        kind="request",
        title_query="Merlin",
        category_hint="tv",
        season_number=6,
    )

    assert filter_matches_for_requested_part([item], matching) == [item]
    assert filter_matches_for_requested_part([item], missing) == []


def test_future_episode_availability_blocks_dashboard_logging() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    intent = SupportIntent(
        kind="issue",
        title_query="Silo",
        category_hint="tv",
        issue_type="missing_episode",
        season_number=3,
        episode_number=8,
    )
    availability = TmdbAvailability(
        found=True,
        title="Silo",
        media_type="tv",
        requested_season_exists=True,
        requested_episode_exists=True,
        season_number=3,
        episode_number=8,
        episode_air_date=date(2026, 9, 4),
        episode_name="The Math Is Rude",
    )

    reply = build_availability_reply(
        intent=intent,
        matches=[],
        settings=settings,
        availability=availability,
        today=date(2026, 8, 14),
    )

    assert availability_blocks_logging(intent, availability, today=date(2026, 8, 14))
    assert reply is not None
    assert "Episode not aired yet" in reply.text
    assert "September 4, 2026" in reply.text
    assert not reply.allow_ai_rewrite


def test_without_tvweb_db_request_points_to_search_page() -> None:
    settings = load_settings({"TVWEB_SITE_BASE_URL": "https://ibox-tv.com"})
    intent = detect_support_intent("where can I find Severance")

    reply = build_support_reply(intent=intent, matches=[], settings=settings)

    assert reply is not None
    assert "Search iBOX TV" in reply.text
    assert any(button.url == "https://ibox-tv.com/?search=Severance" for button in reply.buttons)


def test_search_url_uses_category_domains() -> None:
    settings = load_settings({})

    assert search_url(settings, "naruto", "anime").startswith("https://anime.ibox-tv.com")
    assert search_url(settings, "dune", "movie").startswith("https://movies.ibox-tv.com")


def test_cached_tvweb_lookup_finds_title_without_upstream_query() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    settings = load_settings({})
    with Session(engine) as session:
        session.add(
            TvwebCatalogItem(
                tvweb_id=1,
                title="Avatar",
                title_key="avatar",
                episode_title=None,
                category="movie",
                slug="avatar",
                year=2009,
                rating=7.9,
                download_link=None,
            )
        )
        session.commit()

        intent = detect_support_intent("requesting Avatar")
        assert intent is not None
        matches = search_tvweb_cache(
            session=session, settings=settings, query=intent.title_query or ""
        )

    assert matches
    assert matches[0].title == "Avatar"


def test_cached_tvweb_lookup_uses_conservative_fuzzy_fallback() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    settings = load_settings({})
    with Session(engine) as session:
        session.add(
            TvwebCatalogItem(
                tvweb_id=1,
                title="Avatar",
                title_key="avatar",
                episode_title=None,
                category="movie",
                slug="avatar",
                year=2009,
                rating=7.9,
                download_link=None,
            )
        )
        session.commit()

        matches = search_tvweb_cache(session=session, settings=settings, query="Avater")

    assert matches
    assert matches[0].title == "Avatar"


def test_cached_tvweb_lookup_rejects_ambiguous_or_wrong_first_letter_fuzzy_match() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    settings = load_settings({})
    with Session(engine) as session:
        session.add(
            TvwebCatalogItem(
                tvweb_id=1,
                title="Preacher",
                title_key="preacher",
                episode_title=None,
                category="tv",
                slug="preacher",
                year=2016,
                rating=7.9,
                download_link=None,
            )
        )
        session.commit()

        matches = search_tvweb_cache(session=session, settings=settings, query="Reacher")

    assert matches == []


def test_cached_tvweb_lookup_matches_short_acronym_punctuation() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    settings = load_settings({})
    with Session(engine) as session:
        session.add(
            TvwebCatalogItem(
                tvweb_id=1,
                title="E.R.",
                title_key="e.r",
                episode_title="Season 1",
                category="tv",
                slug="er-season-1",
                year=1994,
                rating=7.9,
                download_link=None,
            )
        )
        session.commit()

        matches = search_tvweb_cache(session=session, settings=settings, query="ER")

    assert matches
    assert matches[0].title == "E.R."


def test_cached_tvweb_lookup_fuzzes_common_title_typo_after_polite_suffix_strip() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    settings = load_settings({})
    with Session(engine) as session:
        session.add(
            TvwebCatalogItem(
                tvweb_id=1,
                title="Grey's Anatomy",
                title_key="grey's anatomy",
                episode_title="Season 1",
                category="tv",
                slug="greys-anatomy-season-1",
                year=2005,
                rating=7.6,
                download_link=None,
            )
        )
        session.commit()

        intent = detect_support_intent("grays anatomy plz", allow_bare_title=True)
        assert intent is not None
        matches = search_tvweb_cache(
            session=session,
            settings=settings,
            query=intent.title_query or "",
        )

    assert matches
    assert matches[0].title == "Grey's Anatomy"


def test_support_responder_selects_hcnsec_chat_config() -> None:
    settings = load_settings(
        {
            "AI_PROVIDER": "hcnsec",
            "HCNSEC_API_KEY": "provider-key",
            "HCNSEC_BASE_URL": "https://api.hcnsec.cn",
            "HCNSEC_MODEL": "deepseek-v4-flash",
        }
    )

    config = select_support_chat_config(settings)

    assert config is not None
    assert config.provider_name == "hcnsec"
    assert config.base_url == "https://api.hcnsec.cn"


async def test_support_responder_uses_factual_reply_when_disabled() -> None:
    settings = load_settings({"SUPPORT_AI_REPLIES": "false"})
    factual = SupportReply(text="Search iBOX TV here:\nhttps://ibox-tv.com/?search=Dune")
    intent = detect_support_intent("where can I find Dune")

    text = await render_support_reply(
        factual_reply=factual,
        intent=intent,
        matches=[],
        settings=settings,
        user_text="where can I find Dune",
    )

    assert text == factual.text
