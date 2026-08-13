from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("sentinelai.audit")


def log_moderation_action(action: str, **fields: Any) -> None:
    safe_fields = {key: value for key, value in fields.items() if "token" not in key.lower()}
    logger.info("moderation_action=%s fields=%s", action, safe_fields)
