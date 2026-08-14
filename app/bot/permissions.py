from __future__ import annotations

from dataclasses import dataclass

from aiogram.exceptions import TelegramAPIError

from app.config import Settings
from app.db.models import Group
from app.db.repositories import chat_is_authorized

ADMIN_STATUSES = {"creator", "administrator"}


@dataclass(frozen=True, slots=True)
class BotPermissions:
    is_admin: bool = False
    can_delete_messages: bool = False
    can_restrict_members: bool = False
    can_invite_users: bool = False
    raw_status: str | None = None
    error: str | None = None


def is_authorized_chat(
    *,
    telegram_chat_id: int,
    settings: Settings,
    group: Group | None = None,
) -> bool:
    if not settings.require_authorized_chats:
        return True
    if settings.chat_is_allowlisted(telegram_chat_id):
        return True
    return chat_is_authorized(group, settings) if group else False


async def get_bot_permissions(bot: object, chat_id: int) -> BotPermissions:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=chat_id, user_id=me.id)
        status = _status_value(getattr(member, "status", None))
        return BotPermissions(
            is_admin=status in ADMIN_STATUSES,
            can_delete_messages=bool(getattr(member, "can_delete_messages", False)),
            can_restrict_members=bool(getattr(member, "can_restrict_members", False)),
            can_invite_users=bool(getattr(member, "can_invite_users", False)),
            raw_status=str(status),
        )
    except TelegramAPIError as exc:
        return BotPermissions(error=str(exc))


async def user_is_chat_admin(bot: object, chat_id: int, user_id: int | None) -> bool:
    if user_id is None:
        return False
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return _status_value(getattr(member, "status", None)) in ADMIN_STATUSES
    except TelegramAPIError:
        return False


def _status_value(status: object) -> str | None:
    value = getattr(status, "value", status)
    return str(value).lower() if value is not None else None


def permissions_warning(permissions: BotPermissions) -> str | None:
    if not permissions.is_admin:
        return "I need to be promoted to group admin before moderation can work."
    missing: list[str] = []
    if not permissions.can_delete_messages:
        missing.append("delete messages")
    if not permissions.can_restrict_members:
        missing.append("ban/restrict users")
    if missing:
        return "Missing Telegram permissions: " + ", ".join(missing) + "."
    return None
