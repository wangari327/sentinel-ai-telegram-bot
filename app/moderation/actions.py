from __future__ import annotations

from dataclasses import dataclass

from aiogram.exceptions import TelegramAPIError

from app.moderation.scoring import Decision


@dataclass(frozen=True, slots=True)
class ActionResult:
    action: str
    delete_status: str = "not_attempted"
    ban_status: str = "not_attempted"
    error: str | None = None


async def execute_telegram_decision(
    *,
    bot: object,
    chat_id: int,
    message_id: int,
    sender_user_id: int | None,
    decision: Decision,
    can_delete: bool,
    can_ban: bool,
) -> ActionResult:
    delete_status = "not_attempted"
    ban_status = "not_attempted"
    errors: list[str] = []

    if decision.delete:
        if not can_delete:
            delete_status = "missing_permission"
            errors.append("missing delete_messages permission")
        else:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                delete_status = "ok"
            except TelegramAPIError as exc:
                delete_status = "failed"
                errors.append(f"delete failed: {exc}")

    if decision.ban:
        if not sender_user_id:
            ban_status = "missing_sender"
            errors.append("cannot ban without sender user id")
        elif not can_ban:
            ban_status = "missing_permission"
            errors.append("missing ban/restrict permission")
        else:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=sender_user_id)
                ban_status = "ok"
            except TelegramAPIError as exc:
                ban_status = "failed"
                errors.append(f"ban failed: {exc}")

    return ActionResult(
        action=decision.action,
        delete_status=delete_status,
        ban_status=ban_status,
        error="; ".join(errors) if errors else None,
    )
