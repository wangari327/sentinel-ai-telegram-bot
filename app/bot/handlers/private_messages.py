from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.callbacks import make_signed_token
from app.bot.keyboards import training_label_keyboard
from app.config import settings
from app.moderation.normalizer import normalize_telegram_message
from app.training.pending import put_pending_training

router = Router(name="private_messages")


@router.message(F.chat.type == "private")
async def on_private_message(message: Message) -> None:
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
