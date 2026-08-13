from __future__ import annotations

import math
from collections import Counter

from sqlalchemy.orm import Session

from app.db import repositories
from app.db.models import TrainingExample


def token_counter(text: str) -> Counter[str]:
    return Counter(token for token in text.casefold().split() if len(token) > 2)


def cosine_similarity(left: str, right: str) -> float:
    a = token_counter(left)
    b = token_counter(right)
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    numerator = sum(a[token] * b[token] for token in shared)
    left_norm = math.sqrt(sum(value * value for value in a.values()))
    right_norm = math.sqrt(sum(value * value for value in b.values()))
    return numerator / (left_norm * right_norm)


def best_similarity(text: str, examples: list[TrainingExample]) -> float:
    if not examples:
        return 0.0
    return max(cosine_similarity(text, example.normalized_text) for example in examples)


def retrieve_examples(
    session: Session,
    *,
    group_id: int,
    normalized_text: str,
    global_enabled: bool,
) -> tuple[list[TrainingExample], list[TrainingExample], float, float]:
    spam = repositories.list_relevant_examples(
        session,
        group_id=group_id,
        normalized_text=normalized_text,
        label="spam",
        global_enabled=global_enabled,
    )
    not_spam = repositories.list_relevant_examples(
        session,
        group_id=group_id,
        normalized_text=normalized_text,
        label="not_spam",
        global_enabled=global_enabled,
    )
    return (
        spam,
        not_spam,
        best_similarity(normalized_text, spam),
        best_similarity(normalized_text, not_spam),
    )
