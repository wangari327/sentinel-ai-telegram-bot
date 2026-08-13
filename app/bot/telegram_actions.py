from __future__ import annotations

from html import escape

from aiogram.exceptions import TelegramAPIError
from sqlalchemy.orm import Session

from app.bot.callbacks import make_signed_token
from app.bot.keyboards import review_keyboard
from app.config import settings
from app.db import repositories
from app.db.session import session_scope


def admin_notification_text(
    *,
    group_title: str | None,
    display_name: str | None,
    username: str | None,
    user_id: int | None,
    action: str,
    ai_label: str | None,
    confidence: float | None,
    reasons: list[str],
    excerpt: str,
    domains: list[str],
) -> str:
    user_bits = display_name or "Unknown user"
    if username:
        user_bits += f" (@{username})"
    if user_id:
        user_bits += f", ID {user_id}"
    return (
        "<b>Suspicious message detected</b>\n\n"
        f"<b>Group:</b> {escape(group_title or 'Unknown group')}\n"
        f"<b>User:</b> {escape(user_bits)}\n"
        f"<b>Action:</b> {escape(action)}\n"
        f"<b>AI label:</b> {escape(ai_label or 'n/a')}\n"
        f"<b>Confidence:</b> {confidence if confidence is not None else 'n/a'}\n"
        f"<b>Reason:</b> {escape(', '.join(reasons[:4]) or 'No concise reason')}\n\n"
        f"<b>Message:</b>\n\"{escape(excerpt[:500])}\"\n\n"
        f"<b>Links/domains:</b> {escape(', '.join(domains) or 'none')}"
    )


async def notify_admin_about_event(
    *,
    bot: object,
    session: Session | None = None,
    admin_user_id: int | None,
    event_id: int,
    group_title: str | None,
    display_name: str | None,
    username: str | None,
    user_id: int | None,
    action: str,
    ai_label: str | None,
    confidence: float | None,
    reasons: list[str],
    excerpt: str,
    domains: list[str],
) -> bool:
    if not admin_user_id:
        return False
    token = make_signed_token(
        event_id=event_id,
        admin_user_id=admin_user_id,
        secret=settings.webhook_secret,
    )
    text = admin_notification_text(
        group_title=group_title,
        display_name=display_name,
        username=username,
        user_id=user_id,
        action=action,
        ai_label=ai_label,
        confidence=confidence,
        reasons=reasons,
        excerpt=excerpt,
        domains=domains,
    )
    try:
        await bot.send_message(
            chat_id=admin_user_id,
            text=text,
            parse_mode="HTML",
            reply_markup=review_keyboard(token),
            disable_web_page_preview=True,
        )
    except TelegramAPIError:
        return False
    if session is not None:
        repositories.create_pending_review(
            session,
            moderation_event_id=event_id,
            admin_user_id=admin_user_id,
            callback_token=token,
        )
        return True
    with session_scope() as local_session:
        repositories.create_pending_review(
            local_session,
            moderation_event_id=event_id,
            admin_user_id=admin_user_id,
            callback_token=token,
        )
    return True
