from app.bot.keyboards import (
    group_management_keyboard,
    moderation_history_keyboard,
    owner_console_keyboard,
    public_support_keyboard,
    support_issues_keyboard,
    support_reply_keyboard,
    support_requests_keyboard,
)
from app.config import load_settings
from app.db.models import Group, ModerationEvent, SupportIssue, SupportRequest
from app.support.assistant import SupportButton


def test_owner_console_has_no_slash_command_required_actions() -> None:
    keyboard = owner_console_keyboard()

    callback_data = {button.callback_data for row in keyboard.inline_keyboard for button in row}

    assert "console:support_status" in callback_data
    assert "console:refresh_tvweb" in callback_data
    assert "console:persistence" in callback_data


def test_public_support_keyboard_has_site_links_and_tutorial_button() -> None:
    keyboard = public_support_keyboard(load_settings({}))

    buttons = [button for row in keyboard.inline_keyboard for button in row]

    assert any(button.url == "https://ibox-tv.com" for button in buttons)
    assert any(button.url == "https://anime.ibox-tv.com" for button in buttons)
    assert any(button.url == "https://movies.ibox-tv.com" for button in buttons)
    assert any(button.callback_data == "public:tutorial" for button in buttons)


def test_support_reply_keyboard_supports_urls_and_callbacks() -> None:
    keyboard = support_reply_keyboard(
        (
            SupportButton(text="Open", url="https://ibox-tv.com/show/avatar"),
            SupportButton(text="Tutorial", callback_data="support:tutorial"),
        )
    )

    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert buttons[0].url == "https://ibox-tv.com/show/avatar"
    assert buttons[1].callback_data == "support:tutorial"


def test_management_keyboards_expose_actions() -> None:
    groups = [
        Group(id=3, telegram_chat_id=-1001, title="Test", type="supergroup", authorized=False)
    ]
    issues = [
        SupportIssue(
            id=4,
            group_id=1,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=7,
            issue_type="broken_link",
            title_query="Lioness",
            category_hint=None,
            status="open",
            normalized_text="Fix Lioness",
        )
    ]
    requests = [
        SupportRequest(
            id=5,
            group_id=1,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=7,
            title_query="Reacher",
            category_hint=None,
            status="open",
            normalized_text="Requesting Reacher",
        )
    ]

    callback_data = {
        button.callback_data
        for keyboard in (
            group_management_keyboard(groups),
            support_issues_keyboard(issues),
            support_requests_keyboard(requests),
        )
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert "group:allow:3" in callback_data
    assert "group:remove:3" in callback_data
    assert "issue:resolve:4" in callback_data
    assert "issue:dismiss:4" in callback_data
    assert "request:resolve:5" in callback_data
    assert "request:dismiss:5" in callback_data


def test_moderation_history_keyboard_exposes_training_review_actions() -> None:
    events = [
        ModerationEvent(
            id=25,
            group_id=1,
            telegram_chat_id=-1001,
            telegram_message_id=99,
            sender_user_id=7,
            normalized_text="Hot Instagram girl got exposed",
            text_hash="abc",
            domains=[],
            ai_label="not_spam",
            ai_confidence=0.6,
            rule_score=0.0,
            final_score=0.4,
            action_taken="allow",
            action_status="ok",
            reasons=[],
            provider_name="mock",
            model_name="mock",
            prompt_version="test",
        )
    ]

    callback_data = {
        button.callback_data
        for row in moderation_history_keyboard(events).inline_keyboard
        for button in row
    }

    assert "event:spam_delete:25" in callback_data
    assert "event:not_spam:25" in callback_data
