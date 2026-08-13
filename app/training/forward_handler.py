from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.training.examples import save_text_example


@dataclass(frozen=True, slots=True)
class ForwardedTrainingResult:
    example_id: int
    original_matched: bool = False


def save_forwarded_training(
    session: Session,
    *,
    text: str,
    label: str,
    admin_user_id: int,
    group_id: int | None = None,
) -> ForwardedTrainingResult:
    example_id = save_text_example(
        session,
        group_id=group_id,
        text=text,
        label=label,
        admin_user_id=admin_user_id,
        source="forwarded_training",
    )
    return ForwardedTrainingResult(example_id=example_id)
