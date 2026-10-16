"""LLM interface used by the stages. Keep it narrow so a fake can stand in for tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import (
    ClaimResult,
    ExtractionOutput,
    FactCheckDecision,
    ReconcileOutput,
    SameClaimVerdict,
    SupportCheck,
    WebEvidence,
)
from ..services.factcheck_api import ClaimReview


@dataclass
class WebSearchOutcome:
    evidence: WebEvidence
    returned_urls: set[str] = field(default_factory=set)
    """Every URL the search tool actually returned. Used to drop hallucinated sources."""


class LLM(Protocol):
    async def extract(
        self,
        image: bytes | None,
        media_type: str | None,
        caption: str | None,
        ocr_text: str | None,
        image_description: str | None = None,
    ) -> ExtractionOutput:
        """`image_description` comes from the local vision model when one ran; a backend whose
        model takes no image input uses it in place of the image."""
        ...

    async def same_claim(self, a: str, b: str) -> SameClaimVerdict: ...

    async def match_fact_checks(
        self, claim: str, reviews: list[ClaimReview]
    ) -> FactCheckDecision: ...

    async def web_evidence(self, claim: str) -> WebSearchOutcome: ...

    async def check_support(self, sentences: list[str], quotes: list[str]) -> SupportCheck: ...

    async def reconcile_claims(self, claims: list[ClaimResult]) -> ReconcileOutput: ...
