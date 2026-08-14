from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import repositories
from app.db.models import Base, ModerationEvent, TvwebCatalogItem
from app.moderation.pipeline import process_group_message


@dataclass(slots=True)
class FakeChat:
    id: int = -1001
    title: str = "Series 2022 Requests"
    type: str = "supergroup"


@dataclass(slots=True)
class FakeUser:
    id: int = 9001
    username: str = "spammer"
    first_name: str = "Spam"
    last_name: str | None = None


@dataclass(slots=True)
class FakeMessage:
    text: str
    message_id: int = 101
    chat: FakeChat = field(default_factory=FakeChat)
    from_user: FakeUser = field(default_factory=FakeUser)
    caption: str | None = None
    entities: list[object] | None = None
    caption_entities: list[object] | None = None
    reply_to_message: object | None = None


@dataclass(slots=True)
class FakePermissions:
    can_delete_messages: bool = True
    can_restrict_members: bool = False


class FakeBot:
    def __init__(self) -> None:
        self.deleted: list[tuple[int, int]] = []
        self.sent: list[dict[str, object]] = []

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        self.deleted.append((chat_id, message_id))

    async def send_message(self, **kwargs: object) -> FakeMessage:
        self.sent.append(kwargs)
        return FakeMessage(text=str(kwargs.get("text") or ""), message_id=202)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


async def test_pipeline_deletes_obvious_no_link_adult_spam() -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "false",
        }
    )
    bot = FakeBot()
    message = FakeMessage(
        text=(
            "BANNED: BABYSITTER forgot to lock the door, she swallowed it all. "
            "Leaked just 5 mins ago - Watch Uncut. FULL. WATCH NOW. WATCH NOW."
        )
    )

    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Series 2022 Requests",
            chat_type="supergroup",
            settings=settings,
        )
        group.setup_completed = True
        result = await process_group_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            permissions=FakePermissions(),
            sender_is_admin=False,
        )
        event = session.scalar(select(ModerationEvent))

    assert result.decision is not None
    assert result.decision.action == "delete"
    assert bot.deleted == [(-1001, 101)]
    assert event is not None
    assert event.ai_label == "spam"


async def test_pipeline_deletes_hot_instagram_adult_bait_even_without_url() -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "false",
        }
    )
    bot = FakeBot()
    message = FakeMessage(text="Hot Instagram girl got exposed 🔥 riding cock like crazy")

    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Series 2022 Requests",
            chat_type="supergroup",
            settings=settings,
        )
        group.setup_completed = True
        result = await process_group_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            permissions=FakePermissions(),
            sender_is_admin=False,
        )

    assert result.decision is not None
    assert result.decision.action == "delete"
    assert bot.deleted == [(-1001, 101)]


async def test_pipeline_replies_to_clear_title_request_from_cache() -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "true",
            "SUPPORT_AI_REPLIES": "false",
            "SUPPORT_REPLY_CLEANUP_SECONDS": "0",
        }
    )
    bot = FakeBot()
    message = FakeMessage(text="Requesting Avatar")

    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Series 2022 Requests",
            chat_type="supergroup",
            settings=settings,
        )
        group.setup_completed = True
        session.add(
            TvwebCatalogItem(
                tvweb_id=77,
                title="Avatar",
                title_key="avatar",
                episode_title=None,
                category="movie",
                slug="avatar",
                year=2009,
                rating=7.9,
                download_link=None,
            )
        )

        result = await process_group_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            permissions=FakePermissions(),
            sender_is_admin=False,
        )

    assert result.support_replied
    assert bot.sent
    assert "Found on iBOX TV" in str(bot.sent[0]["text"])
    assert "Avatar" in str(bot.sent[0]["text"])


async def test_pipeline_clarifies_season_only_reply_instead_of_random_search() -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "true",
            "SUPPORT_AI_REPLIES": "false",
            "SUPPORT_REPLY_CLEANUP_SECONDS": "0",
        }
    )
    bot = FakeBot()
    replied_post = FakeMessage(text="The Walking Dead: Dead City Season 3 Episode 1-7 CLICK HERE")
    message = FakeMessage(text="Season 1", reply_to_message=replied_post)

    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Series 2022 Requests",
            chat_type="supergroup",
            settings=settings,
        )
        group.setup_completed = True
        session.add(
            TvwebCatalogItem(
                tvweb_id=88,
                title="High Desert",
                title_key="high desert",
                episode_title="Season 1 Complete",
                category="tv",
                slug="high-desert-season-1-complete",
                year=2023,
                rating=7.0,
                download_link=None,
            )
        )

        result = await process_group_message(
            message=message,
            bot=bot,
            session=session,
            settings=settings,
            permissions=FakePermissions(),
            sender_is_admin=False,
        )

    assert result.support_replied
    assert bot.sent
    assert "Quick check" in str(bot.sent[0]["text"])
    assert "The Walking Dead" in str(bot.sent[0]["text"])
    assert "High Desert" not in str(bot.sent[0]["text"])
