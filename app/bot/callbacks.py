from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bot.keyboards import (
    group_management_keyboard,
    moderation_history_keyboard,
    owner_console_keyboard,
    support_issues_keyboard,
    support_requests_keyboard,
)
from app.bot.permissions import user_is_chat_admin
from app.bot.support_actions import send_ephemeral_message, send_tutorial_if_available
from app.config import settings
from app.db import repositories
from app.db.models import ModerationEvent
from app.db.session import session_scope
from app.moderation.normalizer import normalize_message_parts
from app.services.tvweb_cache import refresh_tvweb_catalog_cache
from app.support.assistant import friendly_issue_label
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
        "Private support\n"
        f"Enabled: {settings.private_support_enabled}\n"
        f"Silence after abuse count: {settings.private_abuse_silence_after}\n\n"
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


def _mention_user(user_id: int | None, fallback: str = "there") -> str:
    if user_id is None:
        return escape(fallback)
    return f'<a href="tg://user?id={user_id}">{escape(fallback)}</a>'


def _issue_title(issue: object) -> str:
    return str(
        getattr(issue, "matched_title", None)
        or getattr(issue, "title_query", None)
        or getattr(issue, "normalized_text", "that item")
    )


def _request_title(request: object) -> str:
    return str(
        getattr(request, "matched_title", None)
        or getattr(request, "title_query", None)
        or "that title"
    )


def _groups_console_text(groups: list[object], *, prefix: str | None = None) -> str:
    if not groups:
        body = "No groups seen yet."
    else:
        rows = [
            (
                f"#{group.id} | "
                f"{'authorized' if group.authorized else 'pending'} | "
                f"{group.telegram_chat_id} | "
                f"{_short(getattr(group, 'title', None), 32)}"
            )
            for group in groups
        ]
        body = "ID | Status | Chat ID | Title\n" + "\n".join(rows)
    return f"{prefix}\n\n{body}" if prefix else body


def _issues_console_text(issues: list[object]) -> str:
    if not issues:
        return "No open support issues. Suspiciously peaceful."
    return "Open support issues\n" + "\n".join(
        (
            f"#{issue.id} {friendly_issue_label(getattr(issue, 'issue_type', None))} "
            f"x{issue.occurrence_count}: "
            f"{_short(_issue_title(issue), 52)}"
        )
        for issue in issues
    )


def _requests_console_text(requests: list[object]) -> str:
    if not requests:
        return "No open content requests."
    return "Open content requests\n" + "\n".join(
        (f"#{request.id} x{request.occurrence_count}: " f"{_short(_request_title(request), 52)}")
        for request in requests
    )


def _moderation_history_text(events: list[object], *, prefix: str | None = None) -> str:
    if not events:
        body = "No moderation history yet."
    else:
        body = "Recent moderation events\n" + "\n".join(
            (
                f"#{event.id} {event.action_taken} {event.final_score:.2f}"
                f"{' reviewed=' + event.review_result if event.review_result else ''}: "
                f"{_short(event.normalized_text, 52)}"
            )
            for event in events
        )
    return f"{prefix}\n\n{body}" if prefix else body


@router.callback_query(F.data == "public:tutorial")
async def handle_public_tutorial_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None or message.chat.type != "private":
        await _answer(callback, "Use this in private chat.")
        return
    with session_scope() as session:
        sent = await send_tutorial_if_available(
            bot=callback.bot,
            session=session,
            chat_id=message.chat.id,
            settings=settings,
            cleanup=False,
        )
    if sent is None:
        await _answer(callback, "No tutorial is saved yet.")
        return
    await _answer(callback, "Tutorial sent.")


@router.callback_query(F.data.startswith("support:"))
async def handle_support_callback(callback: CallbackQuery) -> None:
    action = (callback.data or "").split(":", 1)[1]
    message = callback.message
    if action == "tutorial":
        if message is None:
            await _answer(callback, "No message context.")
            return
        with session_scope() as session:
            sent = await send_tutorial_if_available(
                bot=callback.bot,
                session=session,
                chat_id=message.chat.id,
                settings=settings,
                reply_to_message_id=getattr(message, "message_id", None),
            )
        if sent is None:
            await _answer(callback, "No tutorial is saved yet.")
            return
        await _answer(callback, "Tutorial sent.")
        return
    if action == "stuck":
        if message is None:
            await _answer(callback, "Tell me the title and what failed.")
            return
        with session_scope() as session:
            await send_ephemeral_message(
                bot=callback.bot,
                session=session,
                chat_id=message.chat.id,
                text=(
                    "<b>Still stuck?</b>\n"
                    "Reply with the title plus what failed: <code>broken link</code>, "
                    "<code>missing episode</code>, <code>banned</code>, or "
                    "<code>not playing</code>. I will file the right thing."
                ),
                settings=settings,
                reply_to_message_id=getattr(message, "message_id", None),
            )
        await _answer(callback, "I asked for the useful bits.")
        return
    if action == "solved":
        await _answer(callback, "Lovely. I will pretend I was calm the whole time.")
        if message is not None:
            try:
                await message.edit_reply_markup(reply_markup=None)
            except TelegramAPIError:
                pass
        return
    await _answer(callback, "Unknown support action.")


@router.callback_query(F.data.startswith("group:"))
async def handle_group_management_callback(callback: CallbackQuery) -> None:
    if not settings.user_is_owner_admin(_callback_user_id(callback)):
        await _answer(callback, "Owner console only.")
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid group action.")
        return
    _, action, group_id_raw = parts
    try:
        group_id = int(group_id_raw)
    except ValueError:
        await _answer(callback, "Invalid group ID.")
        return

    with session_scope() as session:
        if action == "allow":
            group = repositories.set_group_authorized_by_id(session, group_id, True)
            result = "authorized"
        elif action == "deny":
            group = repositories.set_group_authorized_by_id(session, group_id, False)
            result = "deauthorized"
        elif action == "remove":
            group = repositories.get_group_by_id(session, group_id)
            if group is not None:
                repositories.forget_group_data(session, group.id)
            result = "removed"
        else:
            await _answer(callback, "Unknown group action.")
            return
        groups = repositories.list_groups(session)[:10]
        text = _groups_console_text(groups, prefix=f"Group {group_id} {result}.")
        reply_markup = group_management_keyboard(groups)

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=None)
        except TelegramAPIError:
            pass
    await _answer(callback, "Updated.")


@router.callback_query(F.data.startswith("event:"))
async def handle_moderation_event_callback(callback: CallbackQuery) -> None:
    if not settings.user_is_owner_admin(_callback_user_id(callback)):
        await _answer(callback, "Owner console only.")
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid event action.")
        return
    _, action, event_id_raw = parts
    try:
        event_id = int(event_id_raw)
    except ValueError:
        await _answer(callback, "Invalid event ID.")
        return
    if action not in {"spam_delete", "not_spam"}:
        await _answer(callback, "Unknown event action.")
        return

    deleted = False
    user_id = _callback_user_id(callback)
    with session_scope() as session:
        event = session.get(ModerationEvent, event_id)
        if event is None:
            text = "That moderation event is gone."
            events = repositories.list_recent_moderation_events(session, limit=10)
            reply_markup = moderation_history_keyboard(events)
        else:
            normalized = normalize_message_parts(text=event.normalized_text)
            label = "spam" if action == "spam_delete" else "not_spam"
            repositories.save_training_example(
                session,
                group_id=event.group_id,
                label=label,
                normalized_text=normalized.text,
                raw_excerpt=normalized.raw_excerpt,
                text_hash=normalized.text_hash,
                domains=normalized.domains or event.domains,
                telegram_links=normalized.telegram_links,
                features={},
                source=f"history_{action}",
                created_by_admin_id=user_id,
            )
            event.reviewed_by_admin_id = user_id
            event.review_result = action
            if action == "spam_delete":
                try:
                    await callback.bot.delete_message(
                        chat_id=event.telegram_chat_id,
                        message_id=event.telegram_message_id,
                    )
                    deleted = True
                    event.action_taken = "delete_after_review"
                    event.action_status = "ok"
                except TelegramAPIError:
                    event.action_status = "delete_after_review_failed"
                if event.sender_user_id is not None:
                    repositories.record_violation(
                        session,
                        group_id=event.group_id,
                        telegram_user_id=event.sender_user_id,
                        action="history_spam",
                        score=max(event.final_score, 0.95),
                    )
            prefix = (
                f"Saved #{event_id} as spam training. Deleted={deleted}."
                if action == "spam_delete"
                else f"Saved #{event_id} as good training."
            )
            events = repositories.list_recent_moderation_events(session, limit=10)
            text = _moderation_history_text(events, prefix=prefix)
            reply_markup = moderation_history_keyboard(events)

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=None)
        except TelegramAPIError:
            pass
    await _answer(callback, "Training saved.")


@router.callback_query(F.data.startswith("issue:"))
async def handle_issue_management_callback(callback: CallbackQuery) -> None:
    if not settings.user_is_owner_admin(_callback_user_id(callback)):
        await _answer(callback, "Owner console only.")
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid issue action.")
        return
    _, action, issue_id_raw = parts
    try:
        issue_id = int(issue_id_raw)
    except ValueError:
        await _answer(callback, "Invalid issue ID.")
        return

    notice_sent = False
    with session_scope() as session:
        issue = repositories.get_support_issue(session, issue_id)
        if issue is None:
            text = "Issue is already gone. Very mysterious, very tidy."
        elif action == "resolve":
            repositories.set_support_issue_status(session, issue_id, "resolved")
            notice_text = (
                f"{_mention_user(issue.sender_user_id, 'quick update')}: "
                f"{escape(_issue_title(issue))} is marked fixed for "
                f"{escape(friendly_issue_label(issue.issue_type))}. Try it again when you can."
            )
            notice = await send_ephemeral_message(
                bot=callback.bot,
                session=session,
                chat_id=issue.telegram_chat_id,
                text=notice_text,
                settings=settings,
                purpose="support_resolution_notice",
                parse_mode="HTML",
                cleanup=False,
            )
            notice_sent = notice is not None
            text = f"Issue #{issue_id} resolved. Group notice sent={notice_sent}."
        elif action == "dismiss":
            repositories.set_support_issue_status(session, issue_id, "dismissed")
            text = f"Issue #{issue_id} dismissed."
        else:
            await _answer(callback, "Unknown issue action.")
            return
        issues = repositories.list_recent_support_issues(session, limit=10)
        text = f"{text}\n\n{_issues_console_text(issues)}"
        reply_markup = support_issues_keyboard(issues)

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=None)
        except TelegramAPIError:
            pass
    await _answer(callback, "Updated.")


@router.callback_query(F.data.startswith("request:"))
async def handle_request_management_callback(callback: CallbackQuery) -> None:
    if not settings.user_is_owner_admin(_callback_user_id(callback)):
        await _answer(callback, "Owner console only.")
        return
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await _answer(callback, "Invalid request action.")
        return
    _, action, request_id_raw = parts
    try:
        request_id = int(request_id_raw)
    except ValueError:
        await _answer(callback, "Invalid request ID.")
        return

    notice_sent = False
    with session_scope() as session:
        request = repositories.get_support_request(session, request_id)
        if request is None:
            text = "Request is already gone. The dashboard ate its vegetables."
        elif action == "resolve":
            repositories.set_support_request_status(session, request_id, "resolved")
            notice_text = (
                f"{_mention_user(request.sender_user_id, 'quick update')}: "
                f"{escape(_request_title(request))} has been handled. Search iBOX again."
            )
            notice = await send_ephemeral_message(
                bot=callback.bot,
                session=session,
                chat_id=request.telegram_chat_id,
                text=notice_text,
                settings=settings,
                purpose="support_resolution_notice",
                parse_mode="HTML",
                cleanup=False,
            )
            notice_sent = notice is not None
            text = f"Request #{request_id} resolved. Group notice sent={notice_sent}."
        elif action == "dismiss":
            repositories.set_support_request_status(session, request_id, "dismissed")
            text = f"Request #{request_id} dismissed."
        else:
            await _answer(callback, "Unknown request action.")
            return
        requests = repositories.list_recent_support_requests(session, limit=10)
        text = f"{text}\n\n{_requests_console_text(requests)}"
        reply_markup = support_requests_keyboard(requests)

    if callback.message:
        try:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=None)
        except TelegramAPIError:
            pass
    await _answer(callback, "Updated.")


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
                f"Refresh finished. Cached {count} items.\n\n" f"{tvweb_cache_status_text(session)}"
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
    reply_markup = owner_console_keyboard()
    with session_scope() as session:
        if action == "stats":
            groups = repositories.list_groups(session)
            open_issues = repositories.count_open_support_issues(session)
            open_requests = repositories.count_open_support_requests(session)
            events = sum(
                repositories.count_moderation_events(session, group.id) for group in groups
            )
            text = (
                "SentinelAI stats\n"
                f"Groups seen: {len(groups)}\n"
                f"Moderation events: {events}\n"
                f"Open support issues: {open_issues}\n"
                f"Open content requests: {open_requests}"
            )
        elif action == "groups":
            groups = repositories.list_groups(session)[:10]
            text = _groups_console_text(groups)
            reply_markup = group_management_keyboard(groups)
        elif action == "issues":
            issues = repositories.list_recent_support_issues(session, limit=10)
            text = _issues_console_text(issues)
            reply_markup = support_issues_keyboard(issues)
        elif action == "requests":
            requests = repositories.list_recent_support_requests(session, limit=10)
            text = _requests_console_text(requests)
            reply_markup = support_requests_keyboard(requests)
        elif action == "history":
            events = repositories.list_recent_moderation_events(session, limit=10)
            if not events:
                text = "No moderation history yet."
            else:
                text = _moderation_history_text(events)
                reply_markup = moderation_history_keyboard(events)
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
                reply_markup=reply_markup,
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
