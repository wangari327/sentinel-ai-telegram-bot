from __future__ import annotations

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

from app.bot.permissions import user_is_chat_admin
from app.config import settings
from app.db import repositories
from app.db.models import ModerationEvent
from app.db.session import session_scope
from app.moderation.normalizer import normalize_message_parts
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
