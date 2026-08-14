from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models import Group, ModerationEvent, SupportIssue, SupportRequest
from app.support.assistant import SupportButton


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


def owner_console_keyboard(
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    rows = [
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
        [
            InlineKeyboardButton(text="Website DB", callback_data="console:tvweb"),
            InlineKeyboardButton(text="Support status", callback_data="console:support_status"),
        ],
        [
            InlineKeyboardButton(text="Refresh catalog", callback_data="console:refresh_tvweb"),
            InlineKeyboardButton(text="Backups", callback_data="console:persistence"),
        ],
    ]
    if extra_rows:
        rows = [
            *extra_rows,
            [InlineKeyboardButton(text="Console", callback_data="console:stats")],
            *rows,
        ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_management_keyboard(groups: list[Group]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups[:8]:
        if group.authorized:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Deauthorize {group.id}", callback_data=f"group:deny:{group.id}"
                    ),
                    InlineKeyboardButton(
                        text=f"Remove {group.id}", callback_data=f"group:remove:{group.id}"
                    ),
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"Authorize {group.id}", callback_data=f"group:allow:{group.id}"
                    ),
                    InlineKeyboardButton(
                        text=f"Remove {group.id}", callback_data=f"group:remove:{group.id}"
                    ),
                ]
            )
    return owner_console_keyboard(rows)


def support_issues_keyboard(issues: list[SupportIssue]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Fixed {issue.id}", callback_data=f"issue:resolve:{issue.id}"
            ),
            InlineKeyboardButton(
                text=f"Dismiss {issue.id}", callback_data=f"issue:dismiss:{issue.id}"
            ),
        ]
        for issue in issues[:8]
    ]
    return owner_console_keyboard(rows)


def support_requests_keyboard(requests: list[SupportRequest]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Filled {request.id}", callback_data=f"request:resolve:{request.id}"
            ),
            InlineKeyboardButton(
                text=f"Dismiss {request.id}", callback_data=f"request:dismiss:{request.id}"
            ),
        ]
        for request in requests[:8]
    ]
    return owner_console_keyboard(rows)


def support_reply_keyboard(buttons: tuple[SupportButton, ...]) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for button in buttons:
        if button.url:
            current.append(InlineKeyboardButton(text=button.text, url=button.url))
        elif button.callback_data:
            current.append(
                InlineKeyboardButton(text=button.text, callback_data=button.callback_data)
            )
        else:
            continue
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)


def moderation_history_keyboard(events: list[ModerationEvent]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"Spam + delete {event.id}", callback_data=f"event:spam_delete:{event.id}"
            ),
            InlineKeyboardButton(
                text=f"Good {event.id}", callback_data=f"event:not_spam:{event.id}"
            ),
        ]
        for event in events[:6]
    ]
    return owner_console_keyboard(rows)


def public_support_keyboard(settings: object) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Search TV",
                    url=str(settings.tvweb_site_base_url),
                ),
                InlineKeyboardButton(
                    text="Anime",
                    url=str(settings.tvweb_anime_base_url),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Movies",
                    url=str(settings.tvweb_movies_base_url),
                ),
                InlineKeyboardButton(text="Tutorial", callback_data="public:tutorial"),
            ],
        ]
    )
