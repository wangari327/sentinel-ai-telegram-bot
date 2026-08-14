from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.bot.support_actions import send_ephemeral_message
from app.config import load_settings
from app.db.models import Base, BotSentMessage


@dataclass(slots=True)
class FakeSentMessage:
    message_id: int


class FakeBot:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def send_message(self, **kwargs: object) -> FakeSentMessage:
        self.kwargs = kwargs
        return FakeSentMessage(message_id=42)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


async def test_ephemeral_message_can_be_marked_durable() -> None:
    settings = load_settings({"SUPPORT_REPLY_CLEANUP_SECONDS": "60"})
    bot = FakeBot()

    with _session() as session:
        await send_ephemeral_message(
            bot=bot,
            session=session,
            chat_id=-1001,
            text='<a href="tg://user?id=7">quick update</a>: fixed.',
            settings=settings,
            parse_mode="HTML",
            cleanup=False,
        )

        sent = session.scalar(select(BotSentMessage))

    assert sent is not None
    assert sent.delete_after is None
    assert bot.kwargs is not None
    assert bot.kwargs["parse_mode"] == "HTML"

