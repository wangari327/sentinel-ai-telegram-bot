from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def review_keyboard(token: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Delete", callback_data=f"review:delete:{token}"),
            InlineKeyboardButton(text="Delete + Ban", callback_data=f"review:ban:{token}"),
        ],
        [
            InlineKeyboardButton(text="Not spam", callback_data=f"review:notspam:{token}"),
            InlineKeyboardButton(text="Trust user", callback_data=f"review:trust:{token}"),
        ],
        [
            InlineKeyboardButton(
                text="Save spam example", callback_data=f"review:spam_example:{token}"
            ),
            InlineKeyboardButton(
                text="Save good example", callback_data=f"review:good_example:{token}"
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mode_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Normal", callback_data="mode:normal"),
            InlineKeyboardButton(text="Auto-delete", callback_data="mode:auto_delete"),
        ],
        [
            InlineKeyboardButton(text="Silent", callback_data="mode:silent"),
            InlineKeyboardButton(text="Monitor only", callback_data="mode:monitor_only"),
        ],
        [InlineKeyboardButton(text="Aggressive", callback_data="mode:aggressive")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def training_label_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Spam", callback_data=f"train:spam:{token}"),
                InlineKeyboardButton(text="Not spam", callback_data=f"train:not_spam:{token}"),
            ],
            [InlineKeyboardButton(text="Cancel", callback_data=f"train:cancel:{token}")],
        ]
    )


def owner_console_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Stats", callback_data="console:stats"),
                InlineKeyboardButton(text="Groups", callback_data="console:groups"),
            ],
            [
                InlineKeyboardButton(text="Issues", callback_data="console:issues"),
                InlineKeyboardButton(text="Requests", callback_data="console:requests"),
            ],
            [
                InlineKeyboardButton(text="Spam history", callback_data="console:history"),
                InlineKeyboardButton(text="Tutorial", callback_data="console:tutorial"),
            ],
        ]
    )
