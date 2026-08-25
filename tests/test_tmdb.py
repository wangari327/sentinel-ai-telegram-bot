from datetime import date

import httpx

from app.config import load_settings
from app.support import tmdb
from app.support.tmdb import TmdbAvailability


def test_tmdb_availability_states() -> None:
    assert (
        TmdbAvailability(
            found=True,
            media_type="tv",
            season_number=3,
            episode_number=8,
            requested_season_exists=True,
            requested_episode_exists=True,
            episode_air_date=date(2026, 9, 4),
        ).state(date(2026, 8, 14))
        == "future_episode"
    )
    assert (
        TmdbAvailability(
            found=True,
            media_type="tv",
            season_number=3,
            episode_number=8,
            requested_season_exists=True,
            requested_episode_exists=False,
            season_episode_count=7,
        ).state(date(2026, 8, 14))
        == "episode_unlisted"
    )
    assert (
        TmdbAvailability(
            found=True,
            media_type="movie",
            release_date=date(2026, 1, 1),
        ).state(date(2026, 8, 14))
        == "released_movie"
    )


async def test_tmdb_resolver_parses_tv_season_episode(monkeypatch) -> None:
    settings = load_settings({"TMDB_BEARER_TOKEN": "test-token"})
    requested: list[tuple[str, dict[str, object]]] = []

    async def fake_get_json(
        settings: object,
        path: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        requested.append((path, params))
        if path == "/search/tv":
            return {"results": [{"id": 10, "name": "Silo", "media_type": "tv"}]}
        if path == "/tv/10":
            return {
                "id": 10,
                "name": "Silo",
                "first_air_date": "2023-05-05",
                "seasons": [{"season_number": 3, "air_date": "2026-08-28", "episode_count": 8}],
            }
        if path == "/tv/10/season/3":
            return {"episodes": [{"episode_number": 8, "air_date": "2026-09-04", "name": "Finale"}]}
        raise AssertionError(f"unexpected TMDB path {path}")

    monkeypatch.setattr(tmdb, "_get_json", fake_get_json)

    availability = await tmdb.resolve_tmdb_availability(
        settings=settings,
        title_query="Silo",
        category_hint="tv",
        season_number=3,
        episode_number=8,
    )

    assert availability is not None
    assert availability.found
    assert availability.title == "Silo"
    assert availability.episode_air_date == date(2026, 9, 4)
    assert availability.episode_name == "Finale"
    assert [path for path, _ in requested] == ["/search/tv", "/tv/10", "/tv/10/season/3"]


async def test_tmdb_resolver_uses_show_details_for_season_only(monkeypatch) -> None:
    settings = load_settings({"TMDB_BEARER_TOKEN": "test-token"})
    requested: list[tuple[str, dict[str, object]]] = []

    async def fake_get_json(
        settings: object,
        path: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        requested.append((path, params))
        if path == "/search/tv":
            return {"results": [{"id": 10, "name": "Silo", "media_type": "tv"}]}
        if path == "/tv/10":
            return {
                "id": 10,
                "name": "Silo",
                "first_air_date": "2023-05-05",
                "seasons": [{"season_number": 4, "air_date": "2099-06-01", "episode_count": 0}],
            }
        raise AssertionError(f"unexpected TMDB path {path}")

    monkeypatch.setattr(tmdb, "_get_json", fake_get_json)

    availability = await tmdb.resolve_tmdb_availability(
        settings=settings,
        title_query="Silo",
        category_hint="tv",
        season_number=4,
        episode_number=None,
    )

    assert availability is not None
    assert availability.found
    assert availability.state(today=date(2026, 8, 25)) == "future_season"
    assert [path for path, _ in requested] == ["/search/tv", "/tv/10"]


async def test_tmdb_resolver_keeps_season_metadata_when_episode_details_fail(monkeypatch) -> None:
    settings = load_settings({"TMDB_BEARER_TOKEN": "test-token"})

    async def fake_get_json(
        settings: object,
        path: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        if path == "/search/tv":
            return {"results": [{"id": 10, "name": "Silo", "media_type": "tv"}]}
        if path == "/tv/10":
            return {
                "id": 10,
                "name": "Silo",
                "first_air_date": "2023-05-05",
                "seasons": [{"season_number": 3, "air_date": "2026-08-01", "episode_count": 8}],
            }
        if path == "/tv/10/season/3":
            request = httpx.Request("GET", "https://api.themoviedb.org/3/tv/10/season/3")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)
        raise AssertionError(f"unexpected TMDB path {path}")

    monkeypatch.setattr(tmdb, "_get_json", fake_get_json)

    availability = await tmdb.resolve_tmdb_availability(
        settings=settings,
        title_query="Silo",
        category_hint="tv",
        season_number=3,
        episode_number=8,
    )

    assert availability is not None
    assert availability.found
    assert availability.season_air_date == date(2026, 8, 1)
    assert availability.requested_episode_exists is None
    assert availability.state(today=date(2026, 8, 25)) == "unknown_episode_date"
