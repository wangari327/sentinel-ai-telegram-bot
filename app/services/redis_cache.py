from __future__ import annotations

import json
from typing import Any


class RedisCache:
    def __init__(self, redis_url: str | None) -> None:
        self.redis_url = redis_url
        self._client: Any | None = None

    async def client(self) -> Any | None:
        if not self.redis_url:
            return None
        if self._client is None:
            try:
                from redis.asyncio import from_url

                self._client = from_url(self.redis_url, decode_responses=True)
            except (ImportError, OSError, ValueError):
                return None
        return self._client

    async def get_json(self, key: str) -> dict[str, Any] | None:
        client = await self.client()
        if client is None:
            return None
        value = await client.get(key)
        return json.loads(value) if value else None

    async def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        client = await self.client()
        if client is None:
            return
        await client.set(key, json.dumps(value), ex=ttl_seconds)
