from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from app.bot.permissions import get_bot_permissions, user_is_chat_admin
from app.config import settings
from app.db.session import session_scope
from app.moderation.pipeline import process_group_message

router = Router(name="group_messages")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def on_group_message(message: Message) -> None:
    if not message.bot:
        return
    permissions = await get_bot_permissions(message.bot, message.chat.id)
    sender_is_admin = await user_is_chat_admin(
        message.bot,
        message.chat.id,
        message.from_user.id if message.from_user else None,
    )
    with session_scope() as session:
        result = await process_group_message(
            message=message,
            bot=message.bot,
            session=session,
            settings=settings,
            permissions=permissions,
            sender_is_admin=sender_is_admin,
        )
    if result.status == "skipped_unauthorized_chat" and settings.leave_unauthorized_chats:
        try:
            await message.bot.leave_chat(message.chat.id)
        except TelegramAPIError:
            return


@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def on_edited_group_message(message: Message) -> None:
    await on_group_message(message)
