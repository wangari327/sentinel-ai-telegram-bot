from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.support.ibox_search import normalize_title_query


@dataclass(frozen=True, slots=True)
class TmdbAvailability:
    found: bool
    title: str | None = None
    media_type: str | None = None
    tmdb_id: int | None = None
    tmdb_url: str | None = None
    status: str | None = None
    overview: str | None = None
    release_date: date | None = None
    first_air_date: date | None = None
    last_air_date: date | None = None
    next_air_date: date | None = None
    season_number: int | None = None
    episode_number: int | None = None
    requested_season_exists: bool | None = None
    requested_episode_exists: bool | None = None
    season_air_date: date | None = None
    season_episode_count: int | None = None
    episode_air_date: date | None = None
    episode_name: str | None = None
    source_error: str | None = None

    def state(self, today: date | None = None) -> str:
        today = today or datetime.now(tz=UTC).date()
        if not self.found:
            return "not_found"
        if self.media_type == "movie":
            if self.release_date and self.release_date > today:
                return "future_movie"
            if self.release_date:
                return "released_movie"
            return "unknown_movie_date"
        if self.episode_number is not None:
            if self.requested_season_exists is False:
                return "season_unconfirmed"
            if self.requested_episode_exists is False:
                return "episode_unlisted"
            if self.episode_air_date and self.episode_air_date > today:
                return "future_episode"
            if self.episode_air_date:
                return "aired_episode"
            return "unknown_episode_date"
        if self.season_number is not None:
            if self.requested_season_exists is False:
                return "season_unconfirmed"
            if self.season_air_date and self.season_air_date > today:
                return "future_season"
            if self.season_air_date:
                return "aired_season"
            return "unknown_season_date"
        if self.first_air_date and self.first_air_date > today:
            return "future_tv"
        if self.first_air_date:
            return "released_tv"
        return "unknown_tv_date"


_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


async def resolve_tmdb_availability(
    *,
    settings: Settings,
    title_query: str | None,
    category_hint: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> TmdbAvailability | None:
    if not settings.tmdb_metadata_enabled or not settings.tmdb_bearer_token or not title_query:
        return None

    query = normalize_title_query(title_query)
    if len(query) < 2:
        return None

    try:
        search_result = await _search(settings=settings, query=query, category_hint=category_hint)
        if search_result is None:
            return TmdbAvailability(found=False)
        media_type = str(search_result["media_type"])
        tmdb_id = int(search_result["id"])
        details = await _details(settings=settings, media_type=media_type, tmdb_id=tmdb_id)
        return await _availability_from_details(
            settings=settings,
            media_type=media_type,
            tmdb_id=tmdb_id,
            details=details,
            search_result=search_result,
            season_number=season_number,
            episode_number=episode_number,
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return TmdbAvailability(found=False, source_error=str(exc))


async def _search(
    *,
    settings: Settings,
    query: str,
    category_hint: str | None,
) -> dict[str, Any] | None:
    if category_hint == "movie":
        data = await _get_json(
            settings,
            "/search/movie",
            {"query": query, "include_adult": "false", "region": settings.tmdb_region},
        )
        results = [dict(item, media_type="movie") for item in data.get("results", [])]
    elif category_hint == "tv":
        data = await _get_json(
            settings,
            "/search/tv",
            {"query": query, "include_adult": "false"},
        )
        results = [dict(item, media_type="tv") for item in data.get("results", [])]
    else:
        data = await _get_json(
            settings,
            "/search/multi",
            {"query": query, "include_adult": "false", "region": settings.tmdb_region},
        )
        results = [
            item for item in data.get("results", []) if item.get("media_type") in {"movie", "tv"}
        ]
    if not results:
        return None
    query_key = normalize_title_query(query).casefold()

    def score(item: dict[str, Any]) -> tuple[int, float, str]:
        name = _result_title(item)
        key = normalize_title_query(name).casefold()
        exact = int(key == query_key)
        starts = int(key.startswith(query_key))
        preferred = int(category_hint in {None, "anime"} or item.get("media_type") == category_hint)
        popularity = float(item.get("popularity") or 0.0)
        return (exact * 4 + starts * 2 + preferred, popularity, name)

    return max(results, key=score)


async def _details(
    *,
    settings: Settings,
    media_type: str,
    tmdb_id: int,
) -> dict[str, Any]:
    return await _get_json(settings, f"/{media_type}/{tmdb_id}", {"region": settings.tmdb_region})


async def _availability_from_details(
    *,
    settings: Settings,
    media_type: str,
    tmdb_id: int,
    details: dict[str, Any],
    search_result: dict[str, Any],
    season_number: int | None,
    episode_number: int | None,
) -> TmdbAvailability:
    title = _result_title(details) or _result_title(search_result)
    tmdb_url = f"https://www.themoviedb.org/{media_type}/{tmdb_id}"
    if media_type == "movie":
        return TmdbAvailability(
            found=True,
            title=title,
            media_type=media_type,
            tmdb_id=tmdb_id,
            tmdb_url=tmdb_url,
            status=details.get("status"),
            overview=details.get("overview"),
            release_date=_parse_date(
                details.get("release_date") or search_result.get("release_date")
            ),
        )

    season_exists: bool | None = None
    season_air_date: date | None = None
    season_episode_count: int | None = None
    episode_exists: bool | None = None
    episode_air_date: date | None = None
    episode_name: str | None = None
    if season_number is not None:
        season = _find_season(details.get("seasons") or [], season_number)
        season_exists = season is not None
        if season:
            season_air_date = _parse_date(season.get("air_date"))
            season_episode_count = _int_or_none(season.get("episode_count"))
            if episode_number is not None:
                try:
                    season_details = await _get_json(
                        settings,
                        f"/tv/{tmdb_id}/season/{season_number}",
                        {},
                    )
                    episodes = season_details.get("episodes") or []
                except httpx.HTTPError:
                    episodes = None
                if episodes is not None:
                    episode = _find_episode(episodes, episode_number)
                    episode_exists = episode is not None
                    if episode:
                        episode_air_date = _parse_date(episode.get("air_date"))
                        episode_name = episode.get("name")

    next_episode = details.get("next_episode_to_air") or {}
    return TmdbAvailability(
        found=True,
        title=title,
        media_type=media_type,
        tmdb_id=tmdb_id,
        tmdb_url=tmdb_url,
        status=details.get("status"),
        overview=details.get("overview"),
        first_air_date=_parse_date(
            details.get("first_air_date") or search_result.get("first_air_date")
        ),
        last_air_date=_parse_date(details.get("last_air_date")),
        next_air_date=_parse_date(next_episode.get("air_date")),
        season_number=season_number,
        episode_number=episode_number,
        requested_season_exists=season_exists,
        requested_episode_exists=episode_exists,
        season_air_date=season_air_date,
        season_episode_count=season_episode_count,
        episode_air_date=episode_air_date,
        episode_name=episode_name,
    )


async def _get_json(settings: Settings, path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = {
        "language": settings.tmdb_language,
        **{key: value for key, value in params.items() if value is not None and value != ""},
    }
    cache_key = _cache_key(settings, path, query)
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and cached[0] > now:
        return cached[1]

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {settings.tmdb_bearer_token}",
    }
    async with httpx.AsyncClient(timeout=settings.tmdb_timeout_seconds) as client:
        response = await client.get(
            f"{settings.tmdb_base_url.rstrip('/')}{path}",
            params=query,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    ttl = max(settings.tmdb_cache_ttl_seconds, 0)
    if ttl:
        _CACHE[cache_key] = (now + ttl, data)
    return data


def _cache_key(settings: Settings, path: str, params: dict[str, Any]) -> str:
    parts = "&".join(
        f"{quote(str(key))}={quote(str(value))}" for key, value in sorted(params.items())
    )
    return f"{settings.tmdb_base_url.rstrip('/')}{path}?{parts}"


def _result_title(item: dict[str, Any]) -> str:
    return str(
        item.get("title")
        or item.get("name")
        or item.get("original_title")
        or item.get("original_name")
        or ""
    )


def _find_season(seasons: list[dict[str, Any]], season_number: int) -> dict[str, Any] | None:
    for season in seasons:
        if _int_or_none(season.get("season_number")) == season_number:
            return season
    return None


def _find_episode(episodes: list[dict[str, Any]], episode_number: int) -> dict[str, Any] | None:
    for episode in episodes:
        if _int_or_none(episode.get("episode_number")) == episode_number:
            return episode
    return None


def _parse_date(value: object) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
