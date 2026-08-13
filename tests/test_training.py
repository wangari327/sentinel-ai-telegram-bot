from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Group, ModerationEvent
from app.training.forward_handler import save_forwarded_training
from app.training.review_handler import apply_false_positive_correction


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_forwarded_training_flow_saves_example() -> None:
    session = _session()
    example = save_forwarded_training(
        session,
        text="Leaked video https://t.me/scambot?start=x",
        label="spam",
        admin_user_id=1,
    )

    assert example.example_id == 1


def test_false_positive_correction_saves_not_spam_example() -> None:
    session = _session()
    group = Group(telegram_chat_id=-100, title="Test", type="supergroup", authorized=True)
    session.add(group)
    session.flush()
    event = ModerationEvent(
        group_id=group.id,
        telegram_chat_id=-100,
        telegram_message_id=5,
        sender_user_id=9,
        normalized_text="Security discussion about phishing links",
        text_hash="abc",
        domains=[],
        ai_label="spam",
        ai_confidence=0.9,
        rule_score=0.5,
        final_score=0.9,
        action_taken="delete",
        action_status="ok",
        reasons=["test"],
    )
    session.add(event)
    session.flush()

    example_id = apply_false_positive_correction(
        session,
        moderation_event_id=event.id,
        admin_user_id=1,
    )

    assert example_id == 1
    assert event.review_result == "false_positive"
