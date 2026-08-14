from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import repositories
from app.db.models import Base


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_support_issue_merges_same_matched_show_and_keeps_first_reporter() -> None:
    settings = load_settings({})
    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )

        first = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=111,
            issue_type="broken_link",
            title_query="Lioness",
            category_hint="tv",
            normalized_text="Fix Lioness",
            matched_show_id=77,
            matched_title="Lioness - Season 3 Episode 1-2",
        )
        second = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=222,
            issue_type="broken_link",
            title_query="Lioness season 3 episode 1-7",
            category_hint="tv",
            normalized_text="Lioness expired",
            matched_show_id=77,
            matched_title="Lioness - Season 3 Episode 1-7",
        )

        assert second.id == first.id
        assert second.occurrence_count == 2
        assert second.sender_user_id == 111


def test_support_issue_merges_title_variants_without_match() -> None:
    settings = load_settings({})
    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )

        first = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=111,
            issue_type="broken_link",
            title_query="Lioness season 3 episode 1-2",
            category_hint="tv",
            normalized_text="Fix Lioness",
        )
        second = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=222,
            issue_type="broken_link",
            title_query="Fix lioness",
            category_hint="tv",
            normalized_text="Lioness expired",
        )

        assert second.id == first.id
        assert second.occurrence_count == 2


def test_support_issue_keeps_different_seasons_separate() -> None:
    settings = load_settings({})
    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )

        first = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=111,
            issue_type="broken_link",
            title_query="Silo season 3",
            category_hint="tv",
            normalized_text="Fix Silo season 3",
        )
        second = repositories.upsert_support_issue(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=222,
            issue_type="broken_link",
            title_query="Silo season 4",
            category_hint="tv",
            normalized_text="Fix Silo season 4",
        )

        assert second.id != first.id
        assert first.occurrence_count == 1
        assert second.occurrence_count == 1


def test_group_authorization_by_id_and_remove() -> None:
    settings = load_settings({})
    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )

        repositories.set_group_authorized_by_id(session, group.id, True)
        assert repositories.get_group_by_id(session, group.id).authorized

        repositories.forget_group_data(session, group.id)
        assert repositories.get_group_by_id(session, group.id) is None


def test_reviewable_moderation_history_filters_harmless_allows() -> None:
    settings = load_settings({})
    with _session() as session:
        group = repositories.get_or_create_group(
            session,
            telegram_chat_id=-1001,
            title="Group",
            chat_type="supergroup",
            settings=settings,
        )
        repositories.save_moderation_event(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=10,
            sender_user_id=111,
            normalized_text="The Mentalist",
            text_hash="plain",
            domains=[],
            ai_label="not_spam",
            ai_confidence=0.4,
            rule_score=0.0,
            final_score=0.4,
            action_taken="allow",
            action_status="ok",
            reasons=[],
            provider_name="mock",
            model_name="mock",
            prompt_version="test",
        )
        repositories.save_moderation_event(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=11,
            sender_user_id=222,
            normalized_text="Hot Instagram girl got exposed riding cock like crazy",
            text_hash="adult",
            domains=[],
            ai_label="not_spam",
            ai_confidence=0.4,
            rule_score=0.0,
            final_score=0.4,
            action_taken="allow",
            action_status="ok",
            reasons=[],
            provider_name="mock",
            model_name="mock",
            prompt_version="test",
        )
        repositories.save_moderation_event(
            session,
            group_id=group.id,
            telegram_chat_id=-1001,
            telegram_message_id=12,
            sender_user_id=333,
            normalized_text="claim reward verify your account",
            text_hash="spam",
            domains=[],
            ai_label="spam",
            ai_confidence=0.95,
            rule_score=0.5,
            final_score=0.92,
            action_taken="delete",
            action_status="ok",
            reasons=["login phishing wording"],
            provider_name="mock",
            model_name="mock",
            prompt_version="test",
        )

        events = repositories.list_recent_reviewable_moderation_events(session, limit=10)

    texts = {event.normalized_text for event in events}
    assert "The Mentalist" not in texts
    assert "Hot Instagram girl got exposed riding cock like crazy" in texts
    assert "claim reward verify your account" in texts
