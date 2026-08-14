from app.bot.permissions import _status_value, is_authorized_chat
from app.config import load_settings


def test_authorized_chat_allowlist() -> None:
    settings = load_settings(
        {
            "BOT_TOKEN": "x",
            "AUTHORIZED_CHAT_IDS": "-1001, -1002",
            "REQUIRE_AUTHORIZED_CHATS": "true",
        }
    )

    assert is_authorized_chat(telegram_chat_id=-1001, settings=settings)
    assert not is_authorized_chat(telegram_chat_id=-999, settings=settings)


def test_authorized_chat_requirement_can_be_disabled() -> None:
    settings = load_settings({"REQUIRE_AUTHORIZED_CHATS": "false"})

    assert is_authorized_chat(telegram_chat_id=-999, settings=settings)


def test_status_value_accepts_enum_like_status() -> None:
    class Status:
        value = "administrator"

    assert _status_value(Status()) == "administrator"
    assert _status_value("creator") == "creator"
