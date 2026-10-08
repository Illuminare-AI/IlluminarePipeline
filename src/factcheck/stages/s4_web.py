"""Stage 4: web evidence via an LLM with a search tool, validated in code."""
from __future__ import annotations

import re

from ..llm.base import LLM
from ..models import ClaimLabel, ClaimResult, Source, WebEvidence


def _norm_url(u: str) -> str:
    return re.sub(r"[#?].*$", "", u.strip().lower().rstrip("/"))


def validate_web_evidence(
    ev: WebEvidence, returned_urls: set[str], caption: str | None, ocr_text: str
) -> WebEvidence:
    allowed = {_norm_url(u) for u in returned_urls}
    sources: list[Source] = [s for s in ev.sources if _norm_url(s.url) in allowed]

    haystack = f"{caption or ''}\n{ocr_text}"
    spans = [s for s in ev.disputed_spans if s and s in haystack]

    label: ClaimLabel = ev.label
    independent = {re.sub(r"^www\.", "", re.sub(r"^https?://", "", _norm_url(s.url)).split("/")[0])
                   for s in sources}
    if label in ("supported", "refuted") and len(independent) < 2:
        label = "not_enough_evidence"

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", ev.explanation.strip()) if s][:3]
    return WebEvidence(label=label, explanation=" ".join(sentences), sources=sources, disputed_spans=spans)


async def web_evidence(claim: str, llm: LLM, caption: str | None, ocr_text: str) -> ClaimResult:
    outcome = await llm.web_evidence(claim)
    ev = validate_web_evidence(outcome.evidence, outcome.returned_urls, caption, ocr_text)
    return ClaimResult(
        claim=claim,
        label=ev.label,
        explanation=ev.explanation,
        sources=ev.sources,
        disputed_spans=ev.disputed_spans,
        evidence_origin="web",
    )
