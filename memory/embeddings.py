"""Small deterministic embedding helpers for semantic text."""

from __future__ import annotations

import hashlib
import math
import re


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def embed_text(text: str, dimensions: int = 8) -> list[float]:
    """Embed text into a fixed-size, normalized bag-of-tokens vector."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    vector = [0.0] * dimensions
    for token in _tokenize(text):
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dimensions
        vector[bucket] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector

    return [value / norm for value in vector]
