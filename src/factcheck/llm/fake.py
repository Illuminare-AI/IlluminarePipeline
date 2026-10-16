"""Deterministic fake LLM for tests, offline development and the eval harness.

Behaviour is driven by simple keyword rules so tests can set up scenarios without a network.
"""
from __future__ import annotations

import re

from ..models import (
    ClaimResult,
    ExtractionOutput,
    FactCheckDecision,
    ReconcileOutput,
    SameClaimVerdict,
    Source,
    SupportCheck,
    Tactic,
    WebEvidence,
)
from ..services.factcheck_api import ClaimReview
from . import telemetry
from .base import WebSearchOutcome

# Interface text a screenshot carries: the fake skips it the way the prompt tells the real model to.
_METADATA = re.compile(
    r"\b(\d[\d.,]*\s*[kKmM]?\s*(views|likes|reposts|retweets|replies|shares|followers|quotes|bookmarks))\b"
    r"|\b(posted|tweeted|published)\s+(at|on)\b|\d{1,2}:\d{2}\s*(am|pm)\b|\bvia\s+(x|twitter|reddit|facebook|instagram|tiktok)\b"
    r"|^\s*@\w+|·|^\s*r/\w+",
    re.IGNORECASE,
)

_TACTIC_CUES = {
    "urgency": ["share before", "act now", "right now", "immediately", "before it's deleted"],
    "authority": ["scientists say", "experts say", "doctors confirm", "officials"],
    "fear": ["dangerous", "will kill", "deadly", "warning"],
    "promised_reward": ["win", "free money", "giveaway", "get rich"],
}


class FakeLLM:
    def __init__(self) -> None:
        self.web_results: dict[str, WebSearchOutcome] = {}
        self.reconcile_output = ReconcileOutput()
        self.calls: list[str] = []

    def _record(self, op: str, role: str = "judge") -> None:
        self.calls.append(op)
        telemetry.record_call(telemetry.CallRecord(
            provider="fake", model="fake", role=role, op=op, latency_ms=0,
            input_tokens=0, output_tokens=0, stop_reason="end_turn",
        ))

    def set_web_result(self, claim_keyword: str, outcome: WebSearchOutcome) -> None:
        self.web_results[claim_keyword.lower()] = outcome

    async def extract(self, image, media_type, caption, ocr_text, image_description=None) -> ExtractionOutput:
        self._record("extract")
        text = "\n".join(part for part in (caption, ocr_text) if part)
        claims: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):  # OCR lines rarely end in punctuation
            s = sentence.strip()
            if not s or s.endswith("?") or s.lower().startswith(("i think", "lol", "imo")):
                continue
            if _METADATA.search(s):
                continue
            if re.search(r"\d|\b(is|are|was|were|has|have|will)\b", s):
                claims.append(s.rstrip("!"))
        tags = []
        for tactic, cues in _TACTIC_CUES.items():
            for cue in cues:
                idx = text.lower().find(cue)
                if idx >= 0:
                    tags.append(Tactic(tactic=tactic, phrase=text[idx : idx + len(cue)]))
                    break
        return ExtractionOutput(
            image_description="a photo" if image else "",
            claims=claims[:3],
            persuasion=tags,
        )

    async def same_claim(self, a: str, b: str) -> SameClaimVerdict:
        self._record("same_claim")
        norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()
        return SameClaimVerdict(same=norm(a) == norm(b), reason="exact normalised match")

    async def match_fact_checks(self, claim, reviews: list[ClaimReview]) -> FactCheckDecision:
        self._record("match_fact_checks")
        for i, r in enumerate(reviews):
            rating = r.rating.lower()
            if "false" in rating:
                return FactCheckDecision(matches=True, review_index=i, label="refuted")
            if "true" in rating:
                return FactCheckDecision(matches=True, review_index=i, label="supported")
            if "misleading" in rating or "context" in rating:
                return FactCheckDecision(matches=True, review_index=i, label="missing_context")
        return FactCheckDecision(matches=False)

    async def web_evidence(self, claim: str) -> WebSearchOutcome:
        self._record("web_evidence", "search")
        for key, outcome in self.web_results.items():
            if key in claim.lower():
                return outcome
        return WebSearchOutcome(
            evidence=WebEvidence(
                label="not_enough_evidence",
                explanation="No reliable sources were found for this claim.",
                sources=[],
                disputed_spans=[],
            ),
            returned_urls=set(),
        )

    async def reconcile_claims(self, claims: list[ClaimResult]) -> ReconcileOutput:
        self._record("reconcile_claims")
        return self.reconcile_output

    async def check_support(self, sentences, quotes) -> SupportCheck:
        self._record("check_support", "fast")
        # A sentence is "supported" if it shares a word of 5+ letters with any quote, or
        # if it is a hedge sentence about evidence.
        out = []
        qwords = set(re.findall(r"[a-z]{5,}", " ".join(quotes).lower()))
        for s in sentences:
            words = set(re.findall(r"[a-z]{5,}", s.lower()))
            out.append(bool(words & qwords) or "evidence" in s.lower() or not quotes)
        return SupportCheck(supported=out)


def source(url: str, quote: str, title: str = "", publisher: str = "") -> Source:
    return Source(url=url, quote=quote, title=title, publisher=publisher)
