"""In-memory Store so the pipeline runs without Postgres.

The teammate's Postgres implementation must satisfy the same `Store` protocol in models.py:
pgvector for find_claims, a phash column with Hamming distance for find_media.
"""
from __future__ import annotations

import re

from ..models import Card, Post, StoredCheck
from ..services.fingerprint import hamming


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


class InMemoryStore:
    def __init__(self, phash_max_distance: int = 10) -> None:
        self._items: list[StoredCheck] = []
        self.phash_max_distance = phash_max_distance

    async def find_media(self, phash: str) -> list[StoredCheck]:
        out = []
        for item in self._items:
            if item.phash and hamming(item.phash, phash) <= self.phash_max_distance:
                out.append(item)
        return out

    async def find_claims(self, text: str, k: int = 5) -> list[StoredCheck]:
        """Crude token-overlap ranking; stands in for an embedding search."""
        q = _tokens(text)
        if not q:
            return []
        scored = []
        for item in self._items:
            best = 0.0
            for claim in item.claims:
                c = _tokens(claim)
                if c:
                    best = max(best, len(q & c) / len(q | c))
            if best > 0.3:
                scored.append((best, item))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [item for _, item in scored[:k]]

    async def save(self, post: Post, card: Card, phash: str | None) -> None:
        self._items.append(
            StoredCheck(
                check_id=card.check_id,
                caption=post.caption,
                claims=[c.claim for c in card.claims],
                phash=phash,
                card=card,
            )
        )

    def __len__(self) -> int:
        return len(self._items)
