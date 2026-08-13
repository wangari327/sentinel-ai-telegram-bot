from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PendingTraining:
    text: str
    admin_user_id: int
    expires_at: float
    group_id: int | None = None


_PENDING: dict[str, PendingTraining] = {}


def put_pending_training(
    *,
    token: str,
    text: str,
    admin_user_id: int,
    ttl_seconds: int,
    group_id: int | None = None,
) -> None:
    _PENDING[token] = PendingTraining(
        text=text,
        admin_user_id=admin_user_id,
        group_id=group_id,
        expires_at=time.time() + ttl_seconds,
    )


def consume_pending_training(token: str) -> PendingTraining | None:
    pending = _PENDING.pop(token, None)
    if pending is None:
        return None
    if pending.expires_at < time.time():
        return None
    return pending
