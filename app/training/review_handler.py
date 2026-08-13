from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repositories
from app.db.models import ModerationEvent
from app.training.examples import save_text_example


def apply_false_positive_correction(
    session: Session,
    *,
    moderation_event_id: int,
    admin_user_id: int,
) -> int:
    event = session.scalar(
        select(ModerationEvent).where(ModerationEvent.id == moderation_event_id)
    )
    if event is None:
        raise ValueError("moderation event not found")
    event.reviewed_by_admin_id = admin_user_id
    event.review_result = "false_positive"
    return save_text_example(
        session,
        group_id=event.group_id,
        text=event.normalized_text,
        label="not_spam",
        admin_user_id=admin_user_id,
        source="false_positive_correction",
    )


def apply_spam_correction(
    session: Session,
    *,
    moderation_event_id: int,
    admin_user_id: int,
) -> int:
    event = session.scalar(
        select(ModerationEvent).where(ModerationEvent.id == moderation_event_id)
    )
    if event is None:
        raise ValueError("moderation event not found")
    event.reviewed_by_admin_id = admin_user_id
    event.review_result = "spam_confirmed"
    if event.sender_user_id:
        repositories.record_violation(
            session,
            group_id=event.group_id,
            telegram_user_id=event.sender_user_id,
            action="admin_confirmed_spam",
            score=event.final_score,
        )
    return save_text_example(
        session,
        group_id=event.group_id,
        text=event.normalized_text,
        label="spam",
        admin_user_id=admin_user_id,
        source="admin_correction",
    )
