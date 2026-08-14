from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from app.bot.callbacks import make_signed_token
from app.bot.keyboards import owner_console_keyboard, training_label_keyboard
from app.config import settings
from app.db import repositories
from app.db.session import session_scope
from app.moderation.normalizer import normalize_telegram_message
from app.training.pending import put_pending_training

router = Router(name="private_messages")


@router.message(F.chat.type == "private")
async def on_private_message(message: Message) -> None:
    text = message.text or message.caption or ""
    user_id = message.from_user.id if message.from_user else 0
    if text.startswith(("/panel", "/console")):
        if not settings.user_is_owner_admin(user_id):
            await message.answer("Owner console is only available to OWNER_ADMIN_IDS.")
            return
        await message.answer("SentinelAI owner console", reply_markup=owner_console_keyboard())
        return
    if text.startswith(("/authorize", "/deauthorize")):
        if not settings.user_is_owner_admin(user_id):
            await message.answer("Only owner admins can change authorized chats.")
            return
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Usage: /authorize -100123 or /deauthorize -100123")
            return
        try:
            chat_id = int(parts[1].strip())
        except ValueError:
            await message.answer("That chat ID is not a valid integer.")
            return
        authorized = text.startswith("/authorize")
        with session_scope() as session:
            repositories.set_group_authorized(
                session,
                telegram_chat_id=chat_id,
                authorized=authorized,
                settings=settings,
            )
        await message.answer(f"Chat {chat_id} authorized={authorized}.")
        return
    if text.startswith("/tutorial_save"):
        if not settings.user_is_owner_admin(user_id):
            await message.answer("Only an owner admin can save the tutorial.")
            return
        file_id, file_type = _message_file(message)
        if not file_id:
            await message.answer("Attach or forward a video/document with /tutorial_save in the caption.")
            return
        with session_scope() as session:
            repositories.save_tutorial_asset(
                session,
                label="default",
                file_id=file_id,
                file_type=file_type,
                caption=(message.caption or "").replace("/tutorial_save", "").strip() or None,
                source_chat_id=message.chat.id,
                source_message_id=message.message_id,
                created_by_admin_id=user_id,
            )
        if settings.tutorial_dump_chat_id:
            try:
                await message.copy_to(chat_id=settings.tutorial_dump_chat_id)
            except TelegramAPIError:
                await message.answer(
                    "Tutorial saved, but I could not copy it to TUTORIAL_DUMP_CHAT_ID."
                )
                return
        await message.answer("Tutorial saved. I can now send it when users ask how to download/play.")
        return
    if message.text and message.text.startswith("/"):
        return
    normalized = normalize_telegram_message(message)
    if not normalized.text:
        await message.answer("Forward or paste a message with text/caption to train on.")
        return
    token = make_signed_token(
        event_id=0,
        admin_user_id=message.from_user.id if message.from_user else 0,
        secret=settings.webhook_secret,
        ttl_seconds=15 * 60,
    )
    put_pending_training(
        token=token,
        text=normalized.text,
        admin_user_id=message.from_user.id if message.from_user else 0,
        ttl_seconds=15 * 60,
    )
    await message.answer(
        "Add this message as a training example?",
        reply_markup=training_label_keyboard(token),
    )


def _message_file(message: Message) -> tuple[str | None, str]:
    if message.video:
        return message.video.file_id, "video"
    if message.document:
        return message.document.file_id, "document"
    return None, ""
