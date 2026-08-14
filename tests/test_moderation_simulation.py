from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import repositories
from app.db.models import Base, ModerationEvent, SupportIssue, SupportRequest, TvwebCatalogItem
from app.moderation import pipeline
from app.moderation.pipeline import process_group_message
from app.support.tmdb import TmdbAvailability


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


async def test_pipeline_replies_to_media_hint_short_title_from_cache() -> None:
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
    message = FakeMessage(text="ER Series")

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
                tvweb_id=78,
                title="E.R.",
                title_key="e.r",
                episode_title="Season 1",
                category="tv",
                slug="er-season-1",
                year=1994,
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
    assert "E.R." in str(bot.sent[0]["text"])


async def test_pipeline_replies_to_year_title_request_even_when_not_cached() -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "true",
            "SUPPORT_AI_REPLIES": "false",
            "SUPPORT_REPLY_CLEANUP_SECONDS": "0",
            "TVWEB_DATABASE_URL": "postgresql://readonly:pass@example.com:5432/ibox",
        }
    )
    bot = FakeBot()
    message = FakeMessage(text="scam 2004")

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
        request = session.scalar(select(SupportRequest))

    assert result.support_replied
    assert request is not None
    assert request.title_query == "scam 2004"
    assert bot.sent
    assert "request" in str(bot.sent[0]["text"]).casefold()


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


async def test_pipeline_uses_tmdb_future_episode_instead_of_logging_issue(monkeypatch) -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "true",
            "SUPPORT_AI_REPLIES": "false",
            "SUPPORT_REPLY_CLEANUP_SECONDS": "0",
            "TMDB_BEARER_TOKEN": "token",
        }
    )
    bot = FakeBot()
    message = FakeMessage(text="Missing episode 8 Silo season 3")

    async def fake_resolve_tmdb_availability(**kwargs) -> TmdbAvailability:
        return TmdbAvailability(
            found=True,
            title="Silo",
            media_type="tv",
            requested_season_exists=True,
            requested_episode_exists=True,
            season_number=3,
            episode_number=8,
            episode_air_date=date(2099, 9, 4),
        )

    monkeypatch.setattr(pipeline, "resolve_tmdb_availability", fake_resolve_tmdb_availability)

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
                title="Silo",
                title_key="silo",
                episode_title="Season 3 Episode 1-7",
                category="tv",
                slug="silo-season-3-episode-1-7",
                year=2026,
                rating=8.0,
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
        issue = session.scalar(select(SupportIssue))

    assert result.support_replied
    assert issue is None
    assert bot.sent
    assert "Episode not aired yet" in str(bot.sent[0]["text"])


async def test_pipeline_filters_wrong_season_match_before_request_reply(monkeypatch) -> None:
    settings = load_settings(
        {
            "AUTHORIZED_CHAT_IDS": "-1001",
            "DEFAULT_GROUP_MODE": "normal",
            "AI_PROVIDER": "rules_only",
            "AI_FALLBACK_PROVIDER": "rules_only",
            "SUPPORT_ENABLED": "true",
            "SUPPORT_AI_REPLIES": "false",
            "SUPPORT_REPLY_CLEANUP_SECONDS": "0",
            "TMDB_BEARER_TOKEN": "token",
        }
    )
    bot = FakeBot()
    message = FakeMessage(text="Requesting Silo season 4")

    async def fake_resolve_tmdb_availability(**kwargs) -> TmdbAvailability:
        return TmdbAvailability(
            found=True,
            title="Silo",
            media_type="tv",
            requested_season_exists=True,
            season_number=4,
            season_air_date=date(2099, 12, 12),
        )

    monkeypatch.setattr(pipeline, "resolve_tmdb_availability", fake_resolve_tmdb_availability)

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
                title="Silo",
                title_key="silo",
                episode_title="Season 3 Episode 1-7",
                category="tv",
                slug="silo-season-3-episode-1-7",
                year=2026,
                rating=8.0,
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
        request = session.scalar(select(SupportRequest))

    assert result.support_replied
    assert request is None
    assert bot.sent
    assert "Season not aired yet" in str(bot.sent[0]["text"])
    assert "Season 3 Episode 1-7" not in str(bot.sent[0]["text"])
