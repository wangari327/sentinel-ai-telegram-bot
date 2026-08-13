from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repositories
from app.moderation.feature_extractor import extract_features
from app.moderation.normalizer import normalize_message_parts


def save_text_example(
    session: Session,
    *,
    group_id: int | None,
    text: str,
    label: str,
    admin_user_id: int | None,
    source: str,
    global_allowed: bool = False,
) -> int:
    normalized = normalize_message_parts(text=text)
    features = extract_features(normalized)
    example = repositories.save_training_example(
        session,
        group_id=group_id,
        label=label,
        normalized_text=normalized.text,
        raw_excerpt=normalized.raw_excerpt,
        text_hash=normalized.text_hash,
        domains=normalized.domains,
        telegram_links=normalized.telegram_links,
        features=features.to_dict(),
        source=source,
        created_by_admin_id=admin_user_id,
        global_allowed=global_allowed,
    )
    return example.id
