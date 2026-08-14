from app.bot.keyboards import owner_console_keyboard


def test_owner_console_has_no_slash_command_required_actions() -> None:
    keyboard = owner_console_keyboard()

    callback_data = {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    }

    assert "console:support_status" in callback_data
    assert "console:refresh_tvweb" in callback_data
    assert "console:persistence" in callback_data
