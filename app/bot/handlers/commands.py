from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.bot.keyboards import mode_keyboard, owner_console_keyboard, public_support_keyboard
from app.bot.permissions import get_bot_permissions, permissions_warning, user_is_chat_admin
from app.bot.support_actions import send_flow_message
from app.config import settings
from app.db import repositories
from app.db.models import Domain, GroupSettings
from app.db.session import session_scope
from app.support.private_assistant import private_user_help_text

router = Router(name="commands")
MODES = {"normal", "auto_delete", "silent", "monitor_only", "aggressive"}


def _target_group_id(message: Message) -> int:
    return int(message.chat.id)


def _mode_updates(mode_value: str) -> dict[str, object]:
    return {
        "mode": mode_value,
        "auto_delete_enabled": mode_value in {"auto_delete", "silent", "aggressive"},
        "silent_enabled": mode_value == "silent",
    }


async def _require_admin(message: Message) -> bool:
    if message.chat.type == "private":
        return True
    is_admin = await user_is_chat_admin(
        message.bot,
        message.chat.id,
        message.from_user.id if message.from_user else None,
    )
    if not is_admin and not settings.user_is_owner_admin(message.from_user.id if message.from_user else None):
        await message.reply("Only group admins can use this command.")
        return False
    return True


@router.message(Command("start"))
async def start(message: Message) -> None:
    if message.chat.type == "private":
        if settings.user_is_owner_admin(message.from_user.id if message.from_user else None):
            with session_scope() as session:
                await send_flow_message(
                    bot=message.bot,
                    session=session,
                    chat_id=message.chat.id,
                    text="SentinelAI owner console. No slash-command treasure hunt required.",
                    settings=settings,
                    purpose="owner_console_flow",
                    reply_markup=owner_console_keyboard(),
                )
            return
        with session_scope() as session:
            await send_flow_message(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=private_user_help_text(),
                settings=settings,
                purpose="public_support_flow",
                reply_markup=public_support_keyboard(settings),
            )
        return
    await setup(message)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if message.chat.type == "private" and not settings.user_is_owner_admin(
        message.from_user.id if message.from_user else None
    ):
        with session_scope() as session:
            await send_flow_message(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=private_user_help_text(),
                settings=settings,
                purpose="public_support_flow",
                reply_markup=public_support_keyboard(settings),
            )
        return
    await message.answer(
        "Commands: /setup, /status, /mode, /thresholds, /train, /examples, "
        "/trust, /untrust, /ban, /ban_on, /ban_off, /allowdomain, /blockdomain, "
        "/domains, /privacy. "
        "The bot only moderates authorized chats."
    )


@router.message(Command("setup"))
async def setup(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer(
            "Run /setup inside an authorized group. Authorized chats are controlled by "
            "AUTHORIZED_CHAT_IDS or an OWNER_ADMIN_IDS setup user."
        )
        return
    if not await _require_admin(message):
        return
    user_id = message.from_user.id if message.from_user else None
    permissions = await get_bot_permissions(message.bot, message.chat.id)
    warning = permissions_warning(permissions)
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        if not repositories.setup_is_allowed_for_user(group, user_id, settings):
            await message.reply(
                "This chat is not authorized for SentinelAI. Add its chat ID to "
                "AUTHORIZED_CHAT_IDS, or run /setup as an OWNER_ADMIN_IDS user."
            )
            return
        repositories.mark_group_authorized(session, group)
        group.setup_completed = warning is None
        group_settings = repositories.get_or_create_group_settings(session, group, settings)
        if user_id:
            group_settings.notify_admin_user_id = user_id
            repositories.bind_admin(session, group.id, user_id, can_receive_notifications=True)

    if warning:
        await message.reply(
            f"Chat authorized, but setup is incomplete. {warning} I will stay in monitor-only mode."
        )
    else:
        await message.reply(
            "Setup complete. This chat is authorized and protected. "
            "Fresh deployments start in monitor-only mode; use /mode when ready."
        )


@router.message(Command("status"))
async def status(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Status is available inside a group where the bot is present.")
        return
    if not await _require_admin(message):
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        group_settings = repositories.get_or_create_group_settings(session, group, settings)
        counts = repositories.count_examples(session, group.id)
        authorized = repositories.chat_is_authorized(group, settings)
    await message.reply(
        "SentinelAI status\n"
        f"Authorized: {authorized}\n"
        f"Setup completed: {group.setup_completed}\n"
        f"Mode: {group_settings.mode}\n"
        f"Auto-ban enabled: {group_settings.ban_enabled}\n"
        f"Spam examples: {counts['spam']}\n"
        f"Not-spam examples: {counts['not_spam']}"
    )


@router.message(Command("mode"))
async def mode(message: Message) -> None:
    if message.chat.type == "private":
        await message.answer("Run /mode inside an authorized group.")
        return
    if not await _require_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    requested_mode = parts[1].strip().lower() if len(parts) > 1 else None
    if requested_mode and requested_mode not in MODES:
        await message.reply(f"Invalid mode. Use one of: {', '.join(sorted(MODES))}.")
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        if not repositories.chat_is_authorized(group, settings):
            await message.reply("This chat is not authorized. Run /setup first with an authorized admin.")
            return
        group_settings = repositories.get_or_create_group_settings(session, group, settings)
        if requested_mode:
            for name, value in _mode_updates(requested_mode).items():
                setattr(group_settings, name, value)
        current_mode = group_settings.mode
    if requested_mode:
        await message.reply(f"Mode changed to {current_mode}.")
        return
    await message.reply(f"Current mode: {current_mode}", reply_markup=mode_keyboard())


@router.message(Command("thresholds"))
async def thresholds(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        group_settings = repositories.get_or_create_group_settings(session, group, settings)
    await message.reply(
        "Thresholds\n"
        f"Delete: {group_settings.spam_delete_threshold}\n"
        f"Ban: {group_settings.spam_ban_threshold}\n"
        f"Suspicious low/high: {group_settings.suspicious_low_threshold}/"
        f"{group_settings.suspicious_high_threshold}"
    )


@router.message(Command("train"))
async def train(message: Message) -> None:
    if message.chat.type == "private" and not settings.user_is_owner_admin(
        message.from_user.id if message.from_user else None
    ):
        with session_scope() as session:
            await send_flow_message(
                bot=message.bot,
                session=session,
                chat_id=message.chat.id,
                text=private_user_help_text(),
                settings=settings,
                purpose="public_support_flow",
                reply_markup=public_support_keyboard(settings),
            )
        return
    await message.answer(
        "Forward a suspicious or legitimate message to me privately. I will ask whether "
        "to save it as Spam or Not spam for training."
    )


@router.message(Command("examples"))
async def examples(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        counts = repositories.count_examples(session, group.id)
    await message.reply(f"Training examples: spam={counts['spam']}, not_spam={counts['not_spam']}")


@router.message(Command("trust"))
async def trust(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply("Reply to a user's message with /trust.")
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        repositories.trust_user(
            session,
            group_id=group.id,
            telegram_user_id=target.id,
            admin_user_id=message.from_user.id,
            reason="manual /trust",
        )
    await message.reply(f"Trusted user ID {target.id}.")


@router.message(Command("untrust"))
async def untrust(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply("Reply to a user's message with /untrust.")
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        repositories.untrust_user(session, group.id, target.id)
    await message.reply(f"Removed trust for user ID {target.id}.")


@router.message(Command("allowdomain"))
async def allowdomain(message: Message) -> None:
    await _domain_command(message, "allowed")


@router.message(Command("blockdomain"))
async def blockdomain(message: Message) -> None:
    await _domain_command(message, "blocked")


async def _domain_command(message: Message, status_value: str) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(f"Usage: /{status_value.rstrip('ed')}domain example.com")
        return
    domain = parts[1].strip().lower()
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        repositories.set_domain_status(session, group.id, domain, status_value, message.from_user.id)
    await message.reply(f"Domain {domain} marked {status_value}.")


@router.message(Command("domains"))
async def domains(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        rows = session.execute(
            select(Domain.domain, Domain.status)
            .where(Domain.group_id == group.id)
            .limit(50)
        ).all()
    if not rows:
        await message.reply("No domain rules configured.")
        return
    await message.reply("\n".join(f"{domain}: {status}" for domain, status in rows))


@router.message(Command("privacy"))
async def privacy(message: Message) -> None:
    await message.answer(
        "SentinelAI stores compact moderation events for 30 days by default, training "
        "examples until deleted, group settings, trusted users, and domain rules. "
        "Examples stay group-local unless global training is explicitly enabled. "
        "Use /forget_group_data in a group to delete stored group data after confirmation."
    )


@router.message(Command("silent_on"))
async def silent_on(message: Message) -> None:
    await _set_flags(message, silent_enabled=True, mode="silent")


@router.message(Command("silent_off"))
async def silent_off(message: Message) -> None:
    await _set_flags(message, silent_enabled=False, mode="normal")


@router.message(Command("autodelete_on"))
async def autodelete_on(message: Message) -> None:
    await _set_flags(message, auto_delete_enabled=True, mode="auto_delete")


@router.message(Command("autodelete_off"))
async def autodelete_off(message: Message) -> None:
    await _set_flags(message, auto_delete_enabled=False, mode="normal")


@router.message(Command("scan_admins_on"))
async def scan_admins_on(message: Message) -> None:
    await _set_flags(message, scan_admins=True)


@router.message(Command("scan_admins_off"))
async def scan_admins_off(message: Message) -> None:
    await _set_flags(message, scan_admins=False)


@router.message(Command("ban_on"))
async def ban_on(message: Message) -> None:
    await _set_flags(message, ban_enabled=True)


@router.message(Command("ban_off"))
async def ban_off(message: Message) -> None:
    await _set_flags(message, ban_enabled=False)


async def _set_flags(message: Message, **updates: object) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        if not repositories.chat_is_authorized(group, settings):
            await message.reply("This chat is not authorized.")
            return
        group_settings = repositories.get_or_create_group_settings(session, group, settings)
        for name, value in updates.items():
            setattr(group_settings, name, value)
    await message.reply("Settings updated.")


@router.message(Command("ban"))
async def ban(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    target_message = message.reply_to_message
    target = target_message.from_user if target_message else None
    if not target:
        await message.reply("Reply to a user's spam message with /ban.")
        return
    permissions = await get_bot_permissions(message.bot, message.chat.id)
    if not permissions.can_restrict_members:
        await message.reply("I do not have ban/restrict permission.")
        return
    try:
        await message.bot.ban_chat_member(chat_id=message.chat.id, user_id=target.id)
        if permissions.can_delete_messages:
            await message.bot.delete_message(
                chat_id=message.chat.id,
                message_id=target_message.message_id,
            )
    except TelegramAPIError as exc:
        await message.reply(f"Manual ban failed: {exc}")
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        if target_message.text or target_message.caption:
            from app.training.examples import save_text_example

            save_text_example(
                session,
                group_id=group.id,
                text=target_message.text or target_message.caption or "",
                label="spam",
                admin_user_id=message.from_user.id if message.from_user else None,
                source="manual_ban",
            )
        repositories.record_violation(
            session,
            group_id=group.id,
            telegram_user_id=target.id,
            action="manual_ban",
            score=1.0,
        )
    await message.reply(f"Banned user ID {target.id} and saved spam signal.")


@router.message(Command("forget_group_data"))
async def forget_group_data(message: Message) -> None:
    if message.chat.type == "private" or not await _require_admin(message):
        return
    if "CONFIRM" not in (message.text or ""):
        await message.reply("This deletes stored group data. Run /forget_group_data CONFIRM to proceed.")
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        repositories.forget_group_data(session, group.id)
    await message.reply("Stored group data deleted.")


@router.callback_query(F.data.startswith("mode:"))
async def mode_callback(callback) -> None:
    mode_value = (callback.data or "").split(":", 1)[1]
    if mode_value not in MODES:
        await callback.answer("Invalid mode.")
        return
    message = callback.message
    if message is None or message.chat.type == "private":
        await callback.answer("Use this from a group message.")
        return
    if not await user_is_chat_admin(message.bot, message.chat.id, callback.from_user.id):
        await callback.answer("Only group admins can change mode.", show_alert=True)
        return
    with session_scope() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
            settings=settings,
        )
        if not repositories.chat_is_authorized(group, settings):
            await callback.answer("This chat is not authorized.", show_alert=True)
            return
        group_settings = session.scalar(
            select(GroupSettings).where(GroupSettings.group_id == group.id)
        )
        for name, value in _mode_updates(mode_value).items():
            setattr(group_settings, name, value)
    await callback.message.edit_text(f"Mode changed to {mode_value}.")
    await callback.answer("Mode updated.")
