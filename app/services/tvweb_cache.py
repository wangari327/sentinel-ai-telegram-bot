from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db import repositories
from app.db.session import session_scope
from app.logging import get_logger
from app.support.ibox_search import fetch_tvweb_catalog

logger = get_logger(__name__)


def refresh_tvweb_catalog_cache(*, settings: Settings) -> int:
    if not settings.support_enabled or not settings.tvweb_cache_enabled:
        return 0
    if not settings.tvweb_database_url:
        return 0
    with session_scope() as session:
        try:
            items = fetch_tvweb_catalog(
                settings=settings,
                limit=settings.tvweb_cache_refresh_limit,
            )
            count = repositories.replace_tvweb_catalog(session, items)
            logger.info("tvweb catalog cache refreshed with %s items", count)
            return count
        except Exception as exc:
            repositories.record_tvweb_catalog_error(session, str(exc))
            logger.exception("tvweb catalog cache refresh failed")
            return 0


def start_tvweb_cache_loop(*, settings: Settings, poll_seconds: int = 60) -> asyncio.Task[None]:
    async def _loop() -> None:
        await _refresh_if_due(settings=settings, reason="startup", force_if_empty=True)
        last_slot_key: str | None = None
        while True:
            await asyncio.sleep(poll_seconds)
            last_slot_key = await _refresh_if_due(
                settings=settings,
                reason="scheduled",
                last_slot_key=last_slot_key,
            )

    return asyncio.create_task(_loop())


async def _refresh_if_due(
    *,
    settings: Settings,
    reason: str,
    force_if_empty: bool = False,
    last_slot_key: str | None = None,
) -> str | None:
    if not settings.support_enabled or not settings.tvweb_cache_enabled:
        return last_slot_key
    if not settings.tvweb_database_url:
        return last_slot_key

    should_refresh, slot_key = await asyncio.to_thread(
        _refresh_due,
        settings,
        force_if_empty,
        last_slot_key,
    )
    if not should_refresh:
        return slot_key or last_slot_key

    logger.info("tvweb catalog cache refresh due: %s", reason)
    await asyncio.to_thread(refresh_tvweb_catalog_cache, settings=settings)
    return slot_key or last_slot_key


def _refresh_due(
    settings: Settings,
    force_if_empty: bool,
    last_slot_key: str | None,
) -> tuple[bool, str | None]:
    now = datetime.now(tz=UTC)
    with session_scope() as session:
        sync = repositories.get_tvweb_catalog_sync(session)
        cached_count = repositories.count_tvweb_catalog_items(session)
        if force_if_empty and cached_count == 0:
            return True, last_slot_key
        if sync and sync.last_refresh_at:
            last_refresh = _ensure_aware(sync.last_refresh_at)
            interval = timedelta(minutes=settings.tvweb_cache_refresh_interval_minutes)
            if interval.total_seconds() > 0 and now - last_refresh >= interval:
                return True, last_slot_key
        elif settings.tvweb_cache_refresh_interval_minutes > 0:
            return True, last_slot_key

    slot_key = _current_slot_key(now, settings.tvweb_cache_refresh_times)
    if slot_key and slot_key != last_slot_key:
        return True, slot_key
    return False, slot_key or last_slot_key


def _current_slot_key(now: datetime, slots: tuple[str, ...]) -> str | None:
    for slot in slots:
        try:
            hour, minute = (int(part) for part in slot.split(":", 1))
        except ValueError:
            continue
        if now.hour == hour and now.minute == minute:
            return f"{now.date().isoformat()}T{hour:02d}:{minute:02d}"
    return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
