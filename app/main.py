from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request

from app.bot.callbacks import router as callbacks_router
from app.bot.handlers.commands import router as commands_router
from app.bot.handlers.group_messages import router as group_messages_router
from app.bot.handlers.private_messages import router as private_messages_router
from app.bot.support_actions import start_cleanup_loop
from app.config import settings
from app.db.session import init_db
from app.logging import configure_logging, get_logger
from app.services.tvweb_cache import start_tvweb_cache_loop

logger = get_logger(__name__)

bot: Bot | None = None
dispatcher: Dispatcher | None = None
cleanup_task: asyncio.Task[None] | None = None
tvweb_cache_task: asyncio.Task[None] | None = None


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(callbacks_router)
    dp.include_router(commands_router)
    dp.include_router(private_messages_router)
    dp.include_router(group_messages_router)
    return dp


async def set_webhook_if_enabled(bot_instance: Bot) -> None:
    if not settings.auto_set_webhook:
        return
    if not settings.webhook_base_url:
        logger.warning("AUTO_SET_WEBHOOK is true but WEBHOOK_BASE_URL is empty")
        return
    try:
        await bot_instance.set_webhook(settings.webhook_url, drop_pending_updates=False)
        logger.info("Telegram webhook registered")
    except TelegramAPIError:
        logger.exception("Telegram webhook registration failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    if settings.auto_migrate:
        init_db()
    global bot, dispatcher, cleanup_task, tvweb_cache_task
    tvweb_cache_task = start_tvweb_cache_loop(settings=settings)
    if settings.bot_token:
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dispatcher = build_dispatcher()
        cleanup_task = start_cleanup_loop(bot=bot)
        await set_webhook_if_enabled(bot)
    else:
        logger.warning("BOT_TOKEN is empty; webhook will reject Telegram updates")
    yield
    if tvweb_cache_task:
        tvweb_cache_task.cancel()
    if cleanup_task:
        cleanup_task.cancel()
    if bot:
        await bot.session.close()


app = FastAPI(title=settings.project_name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "project": settings.project_name,
        "ai_provider": settings.ai_provider,
        "fallback_provider": settings.ai_fallback_provider,
        "authorized_chat_count": len(settings.authorized_chat_ids),
        "require_authorized_chats": settings.require_authorized_chats,
        "demo_mode": settings.demo_mode,
        "support_enabled": settings.support_enabled,
        "tvweb_cache_enabled": settings.tvweb_cache_enabled,
        "tmdb_metadata_ready": settings.tmdb_metadata_enabled and bool(settings.tmdb_bearer_token),
    }


@app.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request) -> dict[str, bool]:
    if secret != settings.webhook_secret:
        raise HTTPException(status_code=404, detail="not found")
    if bot is None or dispatcher is None:
        raise HTTPException(status_code=503, detail="bot is not configured")
    payload = await request.json()
    logger.info(
        "Telegram webhook update received update_id=%s type=%s chat_id=%s",
        payload.get("update_id", "unknown"),
        _telegram_update_type(payload),
        _telegram_payload_chat_id(payload),
    )
    handled = await dispatch_telegram_update_safely(
        payload=payload,
        bot_instance=bot,
        dispatcher_instance=dispatcher,
    )
    return {"ok": handled}


async def dispatch_telegram_update_safely(
    *,
    payload: dict[str, Any],
    bot_instance: Bot,
    dispatcher_instance: Dispatcher,
) -> bool:
    update_id = payload.get("update_id", "unknown")
    try:
        update = Update.model_validate(payload, context={"bot": bot_instance})
        await dispatcher_instance.feed_update(bot_instance, update)
    except Exception:
        logger.exception("Telegram update failed and was acknowledged: update_id=%s", update_id)
        return False
    return True


def _telegram_update_type(payload: dict[str, Any]) -> str:
    for key in (
        "message",
        "edited_message",
        "channel_post",
        "edited_channel_post",
        "callback_query",
        "inline_query",
        "my_chat_member",
        "chat_member",
    ):
        if key in payload:
            return key
    return "unknown"


def _telegram_payload_chat_id(payload: dict[str, Any]) -> int | str | None:
    update_type = _telegram_update_type(payload)
    update = payload.get(update_type)
    if not isinstance(update, dict):
        return None
    if update_type == "callback_query":
        message = update.get("message")
        if isinstance(message, dict):
            chat = message.get("chat")
            if isinstance(chat, dict):
                return chat.get("id")
        return None
    chat = update.get("chat")
    if isinstance(chat, dict):
        return chat.get("id")
    return None


async def run_polling() -> None:
    configure_logging(settings.log_level)
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required for polling")
    if settings.auto_migrate:
        init_db()
    polling_bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()
    cleanup = start_cleanup_loop(bot=polling_bot)
    tvweb_cache = start_tvweb_cache_loop(settings=settings)
    try:
        await dp.start_polling(polling_bot)
    finally:
        cleanup.cancel()
        tvweb_cache.cancel()
        await polling_bot.session.close()


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
