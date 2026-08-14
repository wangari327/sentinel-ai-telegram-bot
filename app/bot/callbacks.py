from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bot.keyboards import owner_console_keyboard
from app.bot.permissions import user_is_chat_admin
from app.config import settings
from app.db import repositories
from app.db.models import ModerationEvent
from app.db.session import session_scope
from app.moderation.normalizer import normalize_message_parts
from app.services.tvweb_cache import refresh_tvweb_catalog_cache
from app.training.pending import consume_pending_training

router = Router(name="callbacks")


@dataclass(frozen=True, slots=True)
class TokenClaims:
    event_id: int
    admin_user_id: int
    exp: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def make_signed_token(
    *,
    event_id: int,
    admin_user_id: int,
    secret: str,
    ttl_seconds: int = 7 * 24 * 60 * 60,
) -> str:
    payload = {
        "event_id": event_id,
        "admin_user_id": admin_user_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_b64 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64(sig)[:22]}"


def verify_signed_token(token: str, *, secret: str, now: int | None = None) -> TokenClaims:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("invalid callback token format") from exc
    expected = _b64(
        hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    )[:22]
    if not hmac.compare_digest(signature_b64, expected):
        raise ValueError("invalid callback token signature")
    payload = json.loads(_unb64(payload_b64))
    current = int(time.time()) if now is None else now
    if int(payload["exp"]) < current:
        raise ValueError("callback token expired")
    return TokenClaims(
        event_id=int(payload["event_id"]),
        admin_user_id=int(payload["admin_user_id"]),
        exp=int(payload["exp"]),
    )


def callback_user_is_authorized(
    *,
    callback_user_id: int,
    pending_admin_user_id: int,
    is_group_admin: bool,
    owner_admin_ids: set[int] | frozenset[int],
) -> bool:
    return (
        callback_user_id == pending_admin_user_id
        or callback_user_id in owner_admin_ids
        or is_group_admin
    )


async def _answer(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.answer(text, show_alert=False)
    except TelegramAPIError:
        return


def _callback_user_id(callback: CallbackQuery) -> int:
    return callback.from_user.id if callback.from_user else 0


def _short(value: str | None, limit: int = 80) -> str:
    if not value:
        return "-"
    return value if len(value) <= limit else f"{value[: limit - 1]}..."


def _masked(value: str | None) -> str:
    if not value:
        return "not configured"
    if len(value) <= 18:
        return "***configured***"
    return f"{value[:10]}...{value[-6:]}"


def tvweb_config_text(cache_status: str | None = None) -> str:
    status = _masked(settings.tvweb_database_url)
    cache_settings = (
        "AI support intent\n"
        f"Enabled: {settings.support_ai_intent_enabled}\n"
        f"Threshold: {settings.support_ai_intent_threshold}\n"
        f"Max text chars: {settings.support_ai_intent_max_text_chars}\n\n"
        "Cache settings\n"
        f"Enabled: {settings.tvweb_cache_enabled}\n"
        f"Refresh on startup: {settings.tvweb_cache_refresh_on_startup}\n"
        f"Refresh interval minutes: {settings.tvweb_cache_refresh_interval_minutes}\n"
        f"Refresh UTC times: {', '.join(settings.tvweb_cache_refresh_times) or 'none'}\n"
        f"Refresh limit: {settings.tvweb_cache_refresh_limit}"
    )
    if settings.tvweb_database_url:
        text = (
            "Website DB setup\n"
            f"Current TVWEB_DATABASE_URL: {status}\n\n"
            "TVWEB_DATABASE_URL is configured. No need to paste it again unless you "
            "are rotating credentials or switching website databases.\n\n"
            "Sentinel searches the local iBOX catalog cache during group messages, "
            "not the website DB directly. Use /refresh_tvweb_cache to replace the "
            "local cache with a fresh pull from the website DB.\n\n"
            f"{cache_settings}"
        )
    else:
        text = (
            "Website DB setup\n"
            f"Current TVWEB_DATABASE_URL: {status}\n\n"
            "From your website .env, copy the value named DATABASE_URL.\n"
            "Paste it into Sentinel's VPS .env as:\n"
            "TVWEB_DATABASE_URL=PASTE_WEBSITE_DATABASE_URL_HERE\n\n"
            "Do not use MONGO_URI_1, MONGO_URI_2, MONGO_DB_NAME, MONGO_COL_NAME, "
            "or REDIS_URL for this lookup. Sentinel searches the website Postgres "
            "tv_shows table through TVWEB_DATABASE_URL.\n\n"
            "After editing /opt/sentinel-ai-telegram-bot/.env, restart with:\n"
            "docker compose -f compose.vps.yml up -d --build\n\n"
            f"{cache_settings}"
        )
    if cache_status:
        text = f"{text}\n\n{cache_status}"
    return text


def tvweb_cache_status_text(session: Session) -> str:
    sync = repositories.get_tvweb_catalog_sync(session)
    count = repositories.count_tvweb_catalog_items(session)
    if not sync:
        return f"Local cache: {count} items, never refreshed."
    last_refresh = sync.last_refresh_at.isoformat() if sync.last_refresh_at else "never"
    error = f"\nLast refresh error: {_short(sync.last_error, 200)}" if sync.last_error else ""
    return (
        f"Local cache: {count} items.\n"
        f"Last refresh: {last_refresh}\n"
        f"Recorded item count: {sync.item_count}"
        f"{error}"
    )


def persistence_text() -> str:
    status = _masked(settings.database_url)
    return (
        "Data survival\n"
        f"Current bot DATABASE_URL: {status}\n\n"
        "The Docker Postgres volume survives container rebuilds, restarts, and normal "
        "repo updates. It does not survive a full VPS wipe unless you restore a backup.\n\n"
        "For reinstall-proof storage, point Sentinel's DATABASE_URL to an external "
        "Postgres database or run scheduled pg_dump backups off the VPS. MongoDB is not "
        "used by Sentinel's current schema; using it would be a storage rewrite, not a "
        "drop-in env change."
    )


@router.callback_query(F.data.startswith("review:"))
async def handle_review_callback(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid callback.")
        return
    _, action, token = parts
    try:
        claims = verify_signed_token(token, secret=settings.webhook_secret)
    except ValueError:
        await _answer(callback, "This review link is invalid or expired.")
        return

    user_id = callback.from_user.id if callback.from_user else 0
    with session_scope() as session:
        review = repositories.get_pending_review(session, token)
        if review is None:
            await _answer(callback, "This review is no longer pending.")
            return
        event = session.scalar(select(ModerationEvent).where(ModerationEvent.id == claims.event_id))
        if event is None:
            await _answer(callback, "The original moderation event is gone.")
            return
        is_group_admin = await user_is_chat_admin(
            callback.bot,
            event.telegram_chat_id,
            user_id,
        )
        if not callback_user_is_authorized(
            callback_user_id=user_id,
            pending_admin_user_id=review.admin_user_id,
            is_group_admin=is_group_admin,
            owner_admin_ids=settings.owner_admin_ids,
        ):
            await _answer(callback, "Only an authorized group admin can use this.")
            return

        if action in {"spam_example", "delete", "ban"}:
            normalized = normalize_message_parts(text=event.normalized_text)
            repositories.save_training_example(
                session,
                group_id=event.group_id,
                label="spam",
                normalized_text=normalized.text,
                raw_excerpt=normalized.raw_excerpt,
                text_hash=normalized.text_hash,
                domains=event.domains or [],
                telegram_links=normalized.telegram_links,
                features={},
                source=f"review_{action}",
                created_by_admin_id=user_id,
            )
        elif action in {"good_example", "notspam"}:
            normalized = normalize_message_parts(text=event.normalized_text)
            repositories.save_training_example(
                session,
                group_id=event.group_id,
                label="not_spam",
                normalized_text=normalized.text,
                raw_excerpt=normalized.raw_excerpt,
                text_hash=normalized.text_hash,
                domains=event.domains or [],
                telegram_links=normalized.telegram_links,
                features={},
                source=f"review_{action}",
                created_by_admin_id=user_id,
            )

        event.reviewed_by_admin_id = user_id
        event.review_result = action
        review.status = "completed"

    if callback.message:
        try:
            await callback.message.edit_text(f"Review completed: {action}")
        except TelegramAPIError:
            return
    await _answer(callback, "Done.")


@router.callback_query(F.data.startswith("console:"))
async def handle_console_callback(callback: CallbackQuery) -> None:
    if not settings.user_is_owner_admin(_callback_user_id(callback)):
        await _answer(callback, "Owner console only.")
        return
    action = (callback.data or "").split(":", 1)[1]
    if action == "refresh_tvweb":
        await _answer(callback, "Refreshing catalog...")
        count = await asyncio.to_thread(refresh_tvweb_catalog_cache, settings=settings)
        with session_scope() as session:
            text = (
                f"Refresh finished. Cached {count} items.\n\n"
                f"{tvweb_cache_status_text(session)}"
            )
        if callback.message:
            try:
                await callback.message.edit_text(
                    text,
                    reply_markup=owner_console_keyboard(),
                    parse_mode=None,
                )
            except TelegramAPIError:
                pass
        return
    with session_scope() as session:
        if action == "stats":
            groups = repositories.list_groups(session)
            open_issues = repositories.count_open_support_issues(session)
            open_requests = repositories.count_open_support_requests(session)
            events = sum(repositories.count_moderation_events(session, group.id) for group in groups)
            text = (
                "SentinelAI stats\n"
                f"Groups seen: {len(groups)}\n"
                f"Moderation events: {events}\n"
                f"Open support issues: {open_issues}\n"
                f"Open content requests: {open_requests}"
            )
        elif action == "groups":
            groups = repositories.list_groups(session)[:10]
            if not groups:
                text = "No groups seen yet."
            else:
                rows = [
                    f"{'yes' if group.authorized else 'no '} | {group.telegram_chat_id} | {_short(group.title, 32)}"
                    for group in groups
                ]
                text = "Authorized | Chat ID | Title\n" + "\n".join(rows)
        elif action == "issues":
            issues = repositories.list_recent_support_issues(session, limit=10)
            if not issues:
                text = "No support issues logged yet."
            else:
                text = "Recent support issues\n" + "\n".join(
                    f"#{issue.id} {issue.issue_type} x{issue.occurrence_count}: {_short(issue.title_query or issue.normalized_text, 52)}"
                    for issue in issues
                )
        elif action == "requests":
            requests = repositories.list_recent_support_requests(session, limit=10)
            if not requests:
                text = "No content requests logged yet."
            else:
                text = "Recent content requests\n" + "\n".join(
                    f"#{request.id} {request.status} x{request.occurrence_count}: {_short(request.title_query, 52)}"
                    for request in requests
                )
        elif action == "history":
            events = repositories.list_recent_moderation_events(session, limit=10)
            if not events:
                text = "No moderation history yet."
            else:
                text = "Recent moderation events\n" + "\n".join(
                    f"#{event.id} {event.action_taken} {event.final_score:.2f}: {_short(event.normalized_text, 52)}"
                    for event in events
                )
        elif action == "tutorial":
            asset = repositories.get_tutorial_asset(session)
            if asset:
                text = f"Tutorial saved as {asset.file_type}. Forward a new video with /tutorial_save to replace it."
            else:
                text = "No tutorial saved yet. Forward the tutorial video here with /tutorial_save in the caption."
        elif action in {"tvweb", "support_status"}:
            text = tvweb_config_text(tvweb_cache_status_text(session))
        elif action == "persistence":
            text = persistence_text()
        else:
            text = "Unknown console action."
    if callback.message:
        try:
            await callback.message.edit_text(
                text,
                reply_markup=owner_console_keyboard(),
                parse_mode=None,
            )
        except TelegramAPIError:
            pass
    await _answer(callback, "Updated.")


@router.callback_query(F.data.startswith("train:"))
async def handle_training_callback(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid training callback.")
        return
    _, label, token = parts
    if label == "cancel":
        consume_pending_training(token)
        await _answer(callback, "Cancelled.")
        if callback.message:
            await callback.message.edit_text("Training cancelled.")
        return
    if label not in {"spam", "not_spam"}:
        await _answer(callback, "Invalid label.")
        return
    try:
        claims = verify_signed_token(token, secret=settings.webhook_secret)
    except ValueError:
        await _answer(callback, "This training link is invalid or expired.")
        return
    user_id = callback.from_user.id if callback.from_user else 0
    if claims.admin_user_id != user_id and not settings.user_is_owner_admin(user_id):
        await _answer(callback, "Only the admin who submitted this can label it.")
        return
    pending = consume_pending_training(token)
    if pending is None:
        await _answer(callback, "This training item expired.")
        return
    with session_scope() as session:
        normalized = normalize_message_parts(text=pending.text)
        repositories.save_training_example(
            session,
            group_id=pending.group_id,
            label=label,
            normalized_text=normalized.text,
            raw_excerpt=normalized.raw_excerpt,
            text_hash=normalized.text_hash,
            domains=normalized.domains,
            telegram_links=normalized.telegram_links,
            features={},
            source="forwarded_training",
            created_by_admin_id=user_id,
        )
    if callback.message:
        await callback.message.edit_text(f"Saved as {label}.")
    await _answer(callback, "Training example saved.")
