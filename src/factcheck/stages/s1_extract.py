"""Stage 1: one multimodal LLM call with structured output, plus code-side validation.

OCR is performed by the frontend and arrives on `Post.ocr_text`; the LLM is given that text rather
than asked to transcribe the image, and the stage copies it onto the Extraction record.
"""
from __future__ import annotations

from ..llm.base import LLM
from ..models import Extraction, ExtractionOutput, Post, Tactic
from ..services.fingerprint import sniff_media_type


def validate_extraction(
    ex: ExtractionOutput, caption: str | None, ocr_text: str | None = None
) -> Extraction:
    """Enforce the rules the prompt asks for, in code: max three claims, verbatim tactic phrases."""
    ocr_text = ocr_text or ""
    haystack = f"{caption or ''}\n{ocr_text}"
    tactics: list[Tactic] = []
    seen: set[str] = set()
    for t in ex.persuasion:
        if t.phrase and t.phrase in haystack and t.tactic not in seen:
            tactics.append(t)
            seen.add(t.tactic)
    claims = [c.strip() for c in ex.claims if c and c.strip()][:3]
    return Extraction(
        ocr_text=ocr_text, image_description=ex.image_description, claims=claims, persuasion=tactics
    )


async def extract(post: Post, llm: LLM, image_description: str | None = None) -> Extraction:
    media_type = sniff_media_type(post.image) if post.image else None
    extra = {"image_description": image_description} if image_description else {}
    raw = await llm.extract(post.image, media_type, post.caption, post.ocr_text, **extra)
    return validate_extraction(raw, post.caption, post.ocr_text)
