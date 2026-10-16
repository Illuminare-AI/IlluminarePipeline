"""Provider-independent implementation of the `LLM` protocol.

Prompt assembly for the six pipeline calls lives here once. Three chat models fill the roles:
`judge` (extraction, claim matching, cross-claim review), `fast` (report structuring, yes/no
checks) and `search` (stage 4 research, the slowest call). Stage 4 has research modes; `native`
uses the search model's own server-side search tool and is the only mode so far.

Structured output has two rungs. A model with native schema support is asked for the schema
directly. Otherwise the schema goes into the prompt as a JSON instruction. Either way the reply is
validated, and one repair attempt sends the validation error back before the call fails.
"""
from __future__ import annotations

from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

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
from . import prompts, telemetry
from .base import WebSearchOutcome
from .chat import (
    ChatModel,
    ChatRequest,
    ChatResponse,
    Effort,
    ImagePart,
    NativeSearcher,
    Part,
    Role,
)
from .schema import json_instruction, parse_json_reply

T = TypeVar("T", bound=BaseModel)
ResearchMode = Literal["native"]


class GenericLLM:
    def __init__(
        self,
        judge: ChatModel,
        fast: ChatModel,
        search: ChatModel,
        search_max_uses: int = 4,
        research_mode: ResearchMode = "native",
    ) -> None:
        self.judge = judge
        self.fast = fast
        self.search = search
        self.search_max_uses = search_max_uses
        self.research_mode = research_mode
        if research_mode == "native" and not isinstance(search, NativeSearcher):
            raise ValueError(
                f"research mode 'native' needs a search model with a server-side search tool; "
                f"{search.provider}:{search.model} has none"
            )

    # ---------- protocol methods ----------

    async def extract(self, image, media_type, caption, ocr_text, image_description=None) -> ExtractionOutput:
        content: list[Part] = []
        if image is not None and self.judge.capabilities.supports_images:
            content.append(ImagePart(data=image, media_type=media_type or "image/jpeg"))
        elif image is not None:
            telemetry.mark("image_dropped", model=self.judge.model, has_description=bool(image_description))
            content.append(
                "Image description (from a local vision model; the image itself is not available to you):\n"
                f"{image_description or '(none)'}"
            )
        content.append(f"Caption:\n{caption or '(none)'}")
        content.append(f"OCR text (from the client):\n{ocr_text or '(none)'}")
        return await self._structured(
            self.judge, prompts.EXTRACT_SYSTEM, content, ExtractionOutput, effort="medium", op="extract"
        )

    async def same_claim(self, a: str, b: str) -> SameClaimVerdict:
        return await self._structured(
            self.judge, prompts.SAME_CLAIM_SYSTEM, [f"Claim A: {a}\nClaim B: {b}"], SameClaimVerdict,
            effort="low", op="same_claim",
        )

    async def match_fact_checks(self, claim, reviews: list[ClaimReview]) -> FactCheckDecision:
        listing = "\n".join(
            f"[{i}] claim: {r.claim_text!r} | publisher: {r.publisher} | rating: {r.rating!r} | {r.url}"
            for i, r in enumerate(reviews)
        )
        return await self._structured(
            self.judge, prompts.MATCH_FACT_CHECKS_SYSTEM, [f"Claim: {claim}\n\nReviews:\n{listing}"],
            FactCheckDecision, effort="low", op="match_fact_checks",
        )

    async def web_evidence(self, claim: str) -> WebSearchOutcome:
        if self.research_mode != "native":
            raise ValueError(f"unknown research mode {self.research_mode!r}")
        result = await self.search.research(prompts.WEB_SEARCH_SYSTEM, claim, self.search_max_uses)  # type: ignore[attr-defined]
        evidence = await self._structured(
            self.fast, prompts.STRUCTURE_WEB_SYSTEM, [f"Claim: {claim}\n\nReport:\n{result.report}"],
            WebEvidence, effort=None, role="fast", op="structure_web",
        )
        return WebSearchOutcome(evidence=evidence, returned_urls=result.returned_urls)

    async def reconcile_claims(self, claims: list[ClaimResult]) -> ReconcileOutput:
        blocks = []
        for i, c in enumerate(claims):
            lines = [
                f"[{i}] claim: {c.claim}",
                f"    label: {c.label} | evidence origin: {c.evidence_origin}",
                f"    explanation: {c.explanation or '(none)'}",
            ]
            for s in c.sources:
                lines.append(f"    source: {s.url} | {s.publisher or s.title} | quote: {s.quote!r}")
            if not c.sources:
                lines.append("    source: (none)")
            blocks.append("\n".join(lines))
        return await self._structured(
            self.judge, prompts.RECONCILE_SYSTEM, ["\n\n".join(blocks)], ReconcileOutput,
            effort="low", op="reconcile_claims",
        )

    async def check_support(self, sentences: list[str], quotes: list[str]) -> SupportCheck:
        numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))
        qs = "\n".join(f"- {q}" for q in quotes) or "(no quotes)"
        return await self._structured(
            self.fast, prompts.SUPPORT_CHECK_SYSTEM, [f"Sentences:\n{numbered}\n\nQuotes:\n{qs}"],
            SupportCheck, effort=None, role="fast", op="check_support",
        )

    # ---------- structured output ----------

    async def _structured(
        self,
        model: ChatModel,
        system: str,
        content: list[Part],
        schema: type[T],
        *,
        effort: Effort,
        op: str,
        role: Role = "judge",
        max_tokens: int = 4096,
    ) -> T:
        native = model.capabilities.supports_schema
        if not native:
            system = f"{system}\n\n{json_instruction(schema)}"
        req = ChatRequest(
            system=system, content=content, schema=schema if native else None, effort=effort,
            max_tokens=max_tokens, role=role, op=op,
        )
        resp = await model.complete(req)
        try:
            return self._parsed(resp, schema)
        except (ValidationError, ValueError) as exc:
            repair = await model.complete(ChatRequest(
                system=system,
                content=[*content, (
                    f"Your previous reply was:\n{resp.text}\n\nIt was rejected: {exc}\n"
                    "Reply again with only the corrected JSON object."
                )],
                schema=schema if native else None, effort=effort, max_tokens=max_tokens,
                role=role, op=f"{op}:repair",
            ))
            return self._parsed(repair, schema)

    @staticmethod
    def _parsed(resp: ChatResponse, schema: type[T]) -> T:
        if resp.parsed is not None:
            return resp.parsed  # type: ignore[return-value]
        return parse_json_reply(resp.text, schema)
