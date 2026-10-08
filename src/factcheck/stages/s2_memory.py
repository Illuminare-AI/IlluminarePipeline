"""Stage 2: reuse a stored verdict only after an LLM confirms it is the same claim."""
from __future__ import annotations

from ..llm.base import LLM
from ..models import ClaimResult, Store


async def memory_match(claim: str, store: Store, llm: LLM, k: int = 5) -> ClaimResult | None:
    candidates = await store.find_claims(claim, k=k)
    for cand in candidates:
        for stored_claim in cand.card.claims:
            if stored_claim.evidence_origin == "none":
                continue  # never propagate a verdict that had no evidence
            verdict = await llm.same_claim(claim, stored_claim.claim)
            if verdict.same:
                return stored_claim.model_copy(update={"claim": claim, "evidence_origin": "memory"})
    return None
