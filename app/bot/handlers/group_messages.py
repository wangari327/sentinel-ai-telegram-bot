from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from app.bot.permissions import get_bot_permissions, user_is_chat_admin
from app.config import settings
from app.db.session import session_scope
from app.logging import get_logger
from app.moderation.pipeline import process_group_message

router = Router(name="group_messages")
logger = get_logger(__name__)


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
    logger.info(
        "Group message result status=%s chat_id=%s message_id=%s sender_id=%s "
        "sender_is_admin=%s bot_admin=%s can_delete=%s can_restrict=%s score=%.2f "
        "action=%s support_replied=%s",
        result.status,
        message.chat.id,
        message.message_id,
        message.from_user.id if message.from_user else None,
        sender_is_admin,
        permissions.is_admin,
        permissions.can_delete_messages,
        permissions.can_restrict_members,
        result.final_score,
        result.decision.action if result.decision else None,
        result.support_replied,
    )
    if result.status == "skipped_unauthorized_chat" and settings.leave_unauthorized_chats:
        try:
            await message.bot.leave_chat(message.chat.id)
        except TelegramAPIError:
            logger.exception("Failed to leave unauthorized chat chat_id=%s", message.chat.id)
            return


@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def on_edited_group_message(message: Message) -> None:
    await on_group_message(message)
