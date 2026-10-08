"""Stage 3: Google Fact Check Tools lookup, confirmed by an LLM match."""
from __future__ import annotations

from ..llm.base import LLM
from ..models import ClaimResult, Source
from ..services.factcheck_api import ClaimReview, FactCheckClient, keyword_query


async def existing_fact_checks(claim: str, client: FactCheckClient, llm: LLM) -> ClaimResult | None:
    reviews: list[ClaimReview] = []
    seen: set[str] = set()
    for query in (claim, keyword_query(claim)):
        if not query:
            continue
        for r in await client.search(query):
            if r.url and r.url not in seen:
                seen.add(r.url)
                reviews.append(r)
    if not reviews:
        return None
    decision = await llm.match_fact_checks(claim, reviews[:10])
    if not decision.matches or decision.review_index is None or decision.label is None:
        return None
    if not 0 <= decision.review_index < len(reviews):
        return None
    r = reviews[decision.review_index]
    return ClaimResult(
        claim=claim,
        label=decision.label,
        explanation=f"{r.publisher or 'A fact-checker'} rated this claim: {r.rating}.",
        sources=[Source(url=r.url, title=r.title, publisher=r.publisher, rating=r.rating,
                        quote=r.title or r.claim_text)],
        disputed_spans=[],
        evidence_origin="fact_check_api",
    )
