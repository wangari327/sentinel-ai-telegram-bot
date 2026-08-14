from app.bot.handlers.commands import _mode_updates


def test_mode_updates_keep_mode_flags_consistent() -> None:
    assert _mode_updates("monitor_only") == {
        "mode": "monitor_only",
        "auto_delete_enabled": False,
        "silent_enabled": False,
    }
    assert _mode_updates("normal") == {
        "mode": "normal",
        "auto_delete_enabled": False,
        "silent_enabled": False,
    }
    assert _mode_updates("auto_delete") == {
        "mode": "auto_delete",
        "auto_delete_enabled": True,
        "silent_enabled": False,
    }
    assert _mode_updates("silent") == {
        "mode": "silent",
        "auto_delete_enabled": True,
        "silent_enabled": True,
    }
