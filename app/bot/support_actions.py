from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repositories

FLOW_PURPOSES = frozenset({"owner_console_flow", "public_support_flow", "training_flow"})


async def send_ephemeral_message(
    *,
    bot: object,
    session: Session,
    chat_id: int,
    text: str,
    settings: Settings,
    reply_to_message_id: int | None = None,
    purpose: str = "support_reply",
    parse_mode: str | None = "HTML",
    cleanup: bool = True,
    cleanup_seconds: int | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> object | None:
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    except TelegramAPIError:
        return None
    delete_delay = (
        settings.support_reply_cleanup_seconds if cleanup_seconds is None else cleanup_seconds
    )
    if cleanup and delete_delay > 0:
        repositories.record_bot_sent_message(
            session,
            chat_id=chat_id,
            message_id=int(getattr(sent, "message_id", 0)),
            purpose=purpose,
            delete_after=datetime.now(tz=UTC) + timedelta(seconds=delete_delay),
        )
    return sent


async def delete_tracked_messages(
    *,
    bot: object,
    session: Session,
    chat_id: int,
    purposes: set[str] | frozenset[str] | tuple[str, ...],
) -> int:
    deleted = 0
    sent_messages = repositories.list_bot_sent_messages(
        session,
        chat_id=chat_id,
        purposes=purposes,
    )
    for sent in sent_messages:
        try:
            await bot.delete_message(chat_id=sent.chat_id, message_id=sent.message_id)
            deleted += 1
        except TelegramAPIError:
            pass
        repositories.delete_bot_sent_message_record(session, sent.id)
    return deleted


async def send_flow_message(
    *,
    bot: object,
    session: Session,
    chat_id: int,
    text: str,
    settings: Settings,
    purpose: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
    cleanup_previous: bool = True,
) -> object | None:
    if cleanup_previous:
        await delete_tracked_messages(
            bot=bot,
            session=session,
            chat_id=chat_id,
            purposes=FLOW_PURPOSES,
        )
    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramAPIError:
        return None
    repositories.record_bot_sent_message(
        session,
        chat_id=chat_id,
        message_id=int(getattr(sent, "message_id", 0)),
        purpose=purpose,
        delete_after=(
            datetime.now(tz=UTC) + timedelta(seconds=settings.support_reply_cleanup_seconds)
            if settings.support_reply_cleanup_seconds > 0
            else None
        ),
    )
    return sent


async def send_tutorial_if_available(
    *,
    bot: object,
    session: Session,
    chat_id: int,
    settings: Settings,
    reply_to_message_id: int | None = None,
    cleanup: bool = True,
) -> object | None:
    asset = repositories.get_tutorial_asset(session)
    if asset is None:
        return None
    try:
        if asset.file_type == "video":
            sent = await bot.send_video(
                chat_id=chat_id,
                video=asset.file_id,
                caption=asset.caption,
                reply_to_message_id=reply_to_message_id,
            )
        else:
            sent = await bot.send_document(
                chat_id=chat_id,
                document=asset.file_id,
                caption=asset.caption,
                reply_to_message_id=reply_to_message_id,
            )
    except TelegramAPIError:
        return None
    if cleanup and settings.support_reply_cleanup_seconds > 0:
        repositories.record_bot_sent_message(
            session,
            chat_id=chat_id,
            message_id=int(getattr(sent, "message_id", 0)),
            purpose="tutorial_reply",
            delete_after=datetime.now(tz=UTC)
            + timedelta(seconds=settings.support_reply_cleanup_seconds),
        )
    return sent


async def cleanup_due_bot_messages(*, bot: object, session: Session) -> int:
    due = repositories.due_bot_sent_messages(session, datetime.now(tz=UTC))
    deleted = 0
    for sent in due:
        try:
            await bot.delete_message(chat_id=sent.chat_id, message_id=sent.message_id)
            deleted += 1
        except TelegramAPIError:
            pass
        repositories.delete_bot_sent_message_record(session, sent.id)
    return deleted


def schedule_cleanup(*, bot: object, delay_seconds: int) -> None:
    if delay_seconds <= 0:
        return

    async def _run() -> None:
        await asyncio.sleep(delay_seconds + 2)
        from app.db.session import session_scope

        with session_scope() as session:
            await cleanup_due_bot_messages(bot=bot, session=session)

    asyncio.create_task(_run())


def start_cleanup_loop(*, bot: Bot, interval_seconds: int = 60) -> asyncio.Task[None]:
    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            from app.db.session import session_scope

            with session_scope() as session:
                await cleanup_due_bot_messages(bot=bot, session=session)

    return asyncio.create_task(_loop())
