from __future__ import annotations

import hashlib
import math


def local_hash_embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in text.casefold().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
