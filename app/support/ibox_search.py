from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import TvwebCatalogItem


@dataclass(frozen=True, slots=True)
class IboxItem:
    id: int
    title: str
    episode_title: str | None
    category: str
    slug: str
    year: int | None
    rating: float | None
    download_link: str | None
    score: float = 0.0
    source_updated_at: datetime | None = None

    @property
    def display_title(self) -> str:
        if self.episode_title and self.category != "movie":
            return f"{self.title} - {self.episode_title}"
        if self.year:
            return f"{self.title} ({self.year})"
        return self.title


_engine_cache: dict[str, Engine] = {}


def _engine(database_url: str) -> Engine:
    if database_url not in _engine_cache:
        _engine_cache[database_url] = create_engine(database_url, future=True, pool_pre_ping=True)
    return _engine_cache[database_url]


def _base_url(settings: Settings, category: str) -> str:
    if category == "anime":
        return settings.tvweb_anime_base_url.rstrip("/")
    if category == "movie":
        return settings.tvweb_movies_base_url.rstrip("/")
    return settings.tvweb_site_base_url.rstrip("/")


def item_url(settings: Settings, item: IboxItem) -> str:
    return f"{_base_url(settings, item.category)}/show/{item.slug}"


def search_url(settings: Settings, query: str, category: str | None = None) -> str:
    target_category = category or "tv"
    base = _base_url(settings, target_category)
    return f"{base}/?search={quote_plus(query)}"


def normalize_title_query(value: str) -> str:
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"@\w+", " ", value)
    value = re.sub(r"[^\w\s'&.-]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:120]


def search_tvweb(
    *,
    settings: Settings,
    query: str,
    category: str | None = None,
    limit: int = 3,
) -> list[IboxItem]:
    if not settings.tvweb_database_url:
        return []
    clean_query = normalize_title_query(query)
    if len(clean_query) < 2:
        return []
    params: dict[str, object] = {"query": f"%{clean_query}%", "limit": limit}
    category_clause = ""
    if category:
        category_clause = "AND category = :category"
        params["category"] = "movie" if category == "movies" else category
    sql = text(
        f"""
        SELECT id, show_name, episode_title, category, slug, year, rating, download_link, updated_at
        FROM tv_shows
        WHERE show_name ILIKE :query
        {category_clause}
        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        LIMIT :limit
        """
    )
    with _engine(settings.tvweb_database_url).connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [
        IboxItem(
            id=int(row["id"]),
            title=str(row["show_name"]),
            episode_title=row["episode_title"],
            category=str(row["category"]),
            slug=str(row["slug"]),
            year=row["year"],
            rating=row["rating"],
            download_link=row["download_link"],
            source_updated_at=row.get("updated_at"),
        )
        for row in rows
    ]


def fetch_tvweb_catalog(*, settings: Settings, limit: int) -> list[IboxItem]:
    if not settings.tvweb_database_url:
        return []
    sql = text(
        """
        SELECT id, show_name, episode_title, category, slug, year, rating, download_link, updated_at
        FROM tv_shows
        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST
        LIMIT :limit
        """
    )
    with _engine(settings.tvweb_database_url).connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).mappings().all()
    return [
        IboxItem(
            id=int(row["id"]),
            title=str(row["show_name"]),
            episode_title=row["episode_title"],
            category=str(row["category"]),
            slug=str(row["slug"]),
            year=row["year"],
            rating=row["rating"],
            download_link=row["download_link"],
            source_updated_at=row.get("updated_at"),
        )
        for row in rows
    ]


def search_tvweb_cache(
    *,
    session: Session,
    settings: Settings,
    query: str,
    category: str | None = None,
    limit: int = 3,
) -> list[IboxItem]:
    clean_query = normalize_title_query(query)
    if len(clean_query) < 2:
        return []
    query_key = clean_query.casefold()
    pattern = f"%{query_key}%"
    title_lower = func.lower(TvwebCatalogItem.title)
    episode_lower = func.lower(TvwebCatalogItem.episode_title)
    stmt = (
        select(TvwebCatalogItem)
        .where(or_(title_lower.like(pattern), episode_lower.like(pattern)))
        .order_by(
            (TvwebCatalogItem.title_key == query_key).desc(),
            title_lower.like(f"{query_key}%").desc(),
            TvwebCatalogItem.source_updated_at.desc(),
            TvwebCatalogItem.updated_at.desc(),
        )
        .limit(limit)
    )
    if category:
        stmt = stmt.where(TvwebCatalogItem.category == ("movie" if category == "movies" else category))
    rows = session.scalars(stmt).all()
    return [
        IboxItem(
            id=row.tvweb_id,
            title=row.title,
            episode_title=row.episode_title,
            category=row.category,
            slug=row.slug,
            year=row.year,
            rating=row.rating,
            download_link=row.download_link,
            source_updated_at=row.source_updated_at,
        )
        for row in rows
    ]
