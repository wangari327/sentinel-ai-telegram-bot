from __future__ import annotations

from types import SimpleNamespace

from app.bot.handlers.commands import group_debug_text
from app.main import _telegram_payload_chat_id, _telegram_update_type


def test_group_debug_text_includes_delivery_and_permission_clues() -> None:
    text = group_debug_text(
        chat_id=-1001,
        chat_title="Series <Requests>",
        authorized=True,
        allowlisted=True,
        group_authorized=False,
        setup_completed=True,
        group_settings=SimpleNamespace(
            mode="normal",
            auto_delete_enabled=False,
            silent_enabled=False,
            ban_enabled=True,
            scan_admins=False,
            ai_scan_all_messages=False,
            ai_scan_links_only=True,
        ),
        permissions=SimpleNamespace(
            is_admin=True,
            can_delete_messages=True,
            can_restrict_members=False,
            raw_status="administrator",
            error=None,
        ),
        permission_warning="Missing Telegram permissions: ban/restrict users.",
        admin_user_id=762308466,
    )

    assert "SentinelAI group diagnostics" in text
    assert "Chat ID: -1001" in text
    assert "Title: Series <Requests>" in text
    assert "Authorized now: yes" in text
    assert "Can restrict/ban users: no" in text
    assert "BotFather privacy mode" in text


def test_webhook_payload_helpers_extract_message_metadata() -> None:
    payload = {
        "update_id": 1,
        "message": {"chat": {"id": -1001}, "text": "/ping"},
    }

    assert _telegram_update_type(payload) == "message"
    assert _telegram_payload_chat_id(payload) == -1001


def test_webhook_payload_helpers_extract_callback_chat() -> None:
    payload = {
        "update_id": 2,
        "callback_query": {"message": {"chat": {"id": 762308466}}},
    }

    assert _telegram_update_type(payload) == "callback_query"
    assert _telegram_payload_chat_id(payload) == 762308466
