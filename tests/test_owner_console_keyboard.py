from app.bot.keyboards import owner_console_keyboard, public_support_keyboard
from app.config import load_settings


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


def test_public_support_keyboard_has_site_links_and_tutorial_button() -> None:
    keyboard = public_support_keyboard(load_settings({}))

    buttons = [
        button
        for row in keyboard.inline_keyboard
        for button in row
    ]

    assert any(button.url == "https://ibox-tv.com" for button in buttons)
    assert any(button.url == "https://anime.ibox-tv.com" for button in buttons)
    assert any(button.url == "https://movies.ibox-tv.com" for button in buttons)
    assert any(button.callback_data == "public:tutorial" for button in buttons)
