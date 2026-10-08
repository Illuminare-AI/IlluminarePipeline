"""Stage 6: self-check explanations against quoted passages; drop unsupported sentences."""
from __future__ import annotations

import re

from ..llm.base import LLM
from ..models import ClaimResult


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


async def self_check(result: ClaimResult, llm: LLM) -> ClaimResult:
    sentences = split_sentences(result.explanation)
    if not sentences:
        return result
    quotes = [s.quote for s in result.sources if s.quote]
    if not quotes:
        # Nothing to check against. Keep only a neutral statement so no unsupported detail is shown.
        if result.label == "not_enough_evidence":
            return result
        return result.model_copy(update={"explanation": sentences[0]})
    check = await llm.check_support(sentences, quotes)
    flags = list(check.supported) + [False] * (len(sentences) - len(check.supported))
    kept = [s for s, ok in zip(sentences, flags) if ok]
    return result.model_copy(update={"explanation": " ".join(kept)})
