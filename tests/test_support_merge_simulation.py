from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import repositories
from app.db.models import Base
from app.moderation import pipeline
from app.moderation.normalizer import normalize_message_parts
from app.support.assistant import SupportIntent


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


async def test_ai_merge_can_merge_same_title_across_issue_type_labels(monkeypatch) -> None:
    settings = load_settings({})
    seen_candidates: list[dict[str, object]] = []

    async def fake_choose_merge_candidate(**kwargs) -> int:
        seen_candidates.extend(kwargs["candidates"])
        return int(kwargs["candidates"][0]["id"])

    monkeypatch.setattr(pipeline, "choose_support_merge_candidate_with_ai", fake_choose_merge_candidate)

    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )
        existing = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=111,
            issue_type="missing_episode",
            title_query="Lioness season 3 episode 1-2",
            category_hint="tv",
            normalized_text="Lioness episode 1-2 missing",
        )

        merge_id = await pipeline._choose_issue_merge_id(
            session=session,
            settings=settings,
            group_id=group.id,
            intent=SupportIntent(
                kind="issue",
                title_query="Lioness",
                category_hint="tv",
                issue_type="broken_link",
            ),
            normalized=normalize_message_parts(text="Fix Lioness link"),
            matched_show_id=None,
            matched_title=None,
        )
        merged = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=222,
            issue_type="broken_link",
            title_query="Lioness",
            category_hint="tv",
            normalized_text="Fix Lioness link",
            merge_issue_id=merge_id,
        )

    assert seen_candidates
    assert seen_candidates[0]["issue_type"] == "missing_episode"
    assert merge_id == existing.id
    assert merged.id == existing.id
    assert merged.occurrence_count == 2

