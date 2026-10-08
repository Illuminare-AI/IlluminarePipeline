"""Anthropic implementation of the LLM protocol.

Small judgement calls use structured outputs via `messages.parse`. Stage 4 uses the server-side
web search tool in a free-text call, then a second parse call to structure the report. Two calls
are used because the URL allowlist must come from the tool results themselves, not the model.
"""
from __future__ import annotations

import base64

import anthropic

from ..models import Extraction, FactCheckDecision, SameClaimVerdict, SupportCheck, WebEvidence
from ..services.factcheck_api import ClaimReview
from . import prompts
from .base import WebSearchOutcome


class AnthropicLLM:
    def __init__(self, model: str = "claude-opus-5", api_key: str | None = None) -> None:
        self.model = model
        self.client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()

    async def _parse(self, system: str, content, output_format, effort: str = "low", max_tokens=4096):
        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output_format,
            output_config={"effort": effort},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model refused the request")
        return response.parsed_output

    async def extract(self, image, media_type, caption) -> Extraction:
        content: list[dict] = []
        if image is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type or "image/jpeg",
                        "data": base64.standard_b64encode(image).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": f"Caption:\n{caption or '(none)'}"})
        return await self._parse(prompts.EXTRACT_SYSTEM, content, Extraction, effort="medium")

    async def same_claim(self, a: str, b: str) -> SameClaimVerdict:
        return await self._parse(
            prompts.SAME_CLAIM_SYSTEM, f"Claim A: {a}\nClaim B: {b}", SameClaimVerdict
        )

    async def match_fact_checks(self, claim, reviews: list[ClaimReview]) -> FactCheckDecision:
        listing = "\n".join(
            f"[{i}] claim: {r.claim_text!r} | publisher: {r.publisher} | rating: {r.rating!r} | {r.url}"
            for i, r in enumerate(reviews)
        )
        return await self._parse(
            prompts.MATCH_FACT_CHECKS_SYSTEM, f"Claim: {claim}\n\nReviews:\n{listing}", FactCheckDecision
        )

    async def web_evidence(self, claim: str) -> WebSearchOutcome:
        messages = [{"role": "user", "content": f"Claim: {claim}"}]
        returned_urls: set[str] = set()
        report_parts: list[str] = []
        for _ in range(5):  # pause_turn restarts
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=prompts.WEB_SEARCH_SYSTEM,
                messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
                output_config={"effort": "medium"},
            )
            for block in response.content:
                btype = getattr(block, "type", "")
                if btype == "web_search_tool_result":
                    results = getattr(block, "content", None)
                    if isinstance(results, list):  # an error result is an object, not a list
                        for item in results:
                            url = getattr(item, "url", None)
                            if url:
                                returned_urls.add(url)
                elif btype == "text":
                    report_parts.append(block.text)
                    for cit in getattr(block, "citations", None) or []:
                        url = getattr(cit, "url", None)
                        if url:
                            returned_urls.add(url)
            if response.stop_reason == "refusal":
                raise RuntimeError("model refused the request")
            if response.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": response.content})
        report = "\n".join(report_parts).strip()
        evidence = await self._parse(
            prompts.STRUCTURE_WEB_SYSTEM, f"Claim: {claim}\n\nReport:\n{report}", WebEvidence
        )
        return WebSearchOutcome(evidence=evidence, returned_urls=returned_urls)

    async def check_support(self, sentences: list[str], quotes: list[str]) -> SupportCheck:
        numbered = "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))
        qs = "\n".join(f"- {q}" for q in quotes) or "(no quotes)"
        return await self._parse(
            prompts.SUPPORT_CHECK_SYSTEM, f"Sentences:\n{numbered}\n\nQuotes:\n{qs}", SupportCheck
        )
