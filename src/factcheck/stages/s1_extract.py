"""Stage 1: one multimodal LLM call with structured output, plus code-side validation."""
from __future__ import annotations

from ..llm.base import LLM
from ..models import Extraction, Post, Tactic
from ..services.fingerprint import sniff_media_type


def validate_extraction(ex: Extraction, caption: str | None) -> Extraction:
    """Enforce the rules the prompt asks for, in code: max three claims, verbatim tactic phrases."""
    haystack = f"{caption or ''}\n{ex.ocr_text}"
    tactics: list[Tactic] = []
    seen: set[str] = set()
    for t in ex.persuasion:
        if t.phrase and t.phrase in haystack and t.tactic not in seen:
            tactics.append(t)
            seen.add(t.tactic)
    claims = [c.strip() for c in ex.claims if c and c.strip()][:3]
    return Extraction(
        ocr_text=ex.ocr_text, image_description=ex.image_description, claims=claims, persuasion=tactics
    )


async def extract(post: Post, llm: LLM) -> Extraction:
    media_type = sniff_media_type(post.image) if post.image else None
    raw = await llm.extract(post.image, media_type, post.caption)
    return validate_extraction(raw, post.caption)
