"""Stage 0: perceptual hash and memory lookup by image. No LLM."""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Post, Store, StoredCheck
from ..services.fingerprint import phash


@dataclass
class FingerprintResult:
    phash: str | None
    media_match: StoredCheck | None


def captions_near_identical(a: str | None, b: str | None) -> bool:
    na = " ".join((a or "").lower().split())
    nb = " ".join((b or "").lower().split())
    if na == nb:
        return True
    if not na or not nb:
        return False
    sa, sb = set(na.split()), set(nb.split())
    return len(sa & sb) / len(sa | sb) >= 0.9


async def fingerprint(post: Post, store: Store) -> FingerprintResult:
    if not post.image:
        return FingerprintResult(phash=None, media_match=None)
    h = phash(post.image)
    candidates = await store.find_media(h)
    for cand in candidates:
        if captions_near_identical(cand.caption, post.caption):
            return FingerprintResult(phash=h, media_match=cand)
    return FingerprintResult(phash=h, media_match=None)
