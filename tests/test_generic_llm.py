"""GenericLLM: prompt assembly per role, research delegation, and the structured-output ladder."""
import json
from dataclasses import dataclass, field

import pytest

from factcheck.llm.chat import Capabilities, ChatRequest, ChatResponse, ImagePart, ResearchResult
from factcheck.llm.generic_llm import GenericLLM
from factcheck.models import SameClaimVerdict, Source, WebEvidence


@dataclass
class StubChat:
    model: str = "stub"
    provider: str = "stub"
    capabilities: Capabilities = field(default_factory=Capabilities)
    replies: list = field(default_factory=list)
    requests: list = field(default_factory=list)

    async def complete(self, req: ChatRequest) -> ChatResponse:
        self.requests.append(req)
        reply = self.replies.pop(0)
        return reply if isinstance(reply, ChatResponse) else ChatResponse(parsed=reply)


@dataclass
class StubSearcher(StubChat):
    capabilities: Capabilities = field(default_factory=lambda: Capabilities(native_search=True))
    researched: list = field(default_factory=list)

    async def research(self, system, claim, max_uses):
        self.researched.append((system, claim, max_uses))
        return ResearchResult(report="REPORT", returned_urls={"https://a.org/x"})


def _llm(judge=None, fast=None, search=None):
    return GenericLLM(judge or StubChat(), fast or StubChat(), search or StubSearcher(), search_max_uses=3)


async def test_extract_sends_image_caption_and_ocr_to_the_judge_at_medium_effort():
    judge = StubChat(replies=[SameClaimVerdict(same=True)])
    await _llm(judge=judge).extract(b"img", "image/png", "cap", "ocr")
    req = judge.requests[0]
    assert isinstance(req.content[0], ImagePart) and req.content[0].media_type == "image/png"
    assert req.content[1:] == ["Caption:\ncap", "OCR text (from the client):\nocr"]
    assert req.effort == "medium" and req.role == "judge" and req.op == "extract"


async def test_extract_gives_a_text_only_model_the_local_description():
    from factcheck.llm import telemetry

    judge = StubChat(capabilities=Capabilities(supports_images=False), replies=[SameClaimVerdict(same=True)] * 2)
    col, token = telemetry.activate()
    try:
        await _llm(judge=judge).extract(b"img", "image/png", None, None, image_description="a cat on a sofa")
        await _llm(judge=judge).extract(None, None, "cap", None)
    finally:
        telemetry.deactivate(token)
    first = judge.requests[0].content
    assert first[0].startswith("Image description") and first[0].endswith("a cat on a sofa")
    assert first[1:] == ["Caption:\n(none)", "OCR text (from the client):\n(none)"]
    assert judge.requests[1].content == ["Caption:\ncap", "OCR text (from the client):\n(none)"]
    assert col.marks == [{"kind": "image_dropped", "model": "stub", "has_description": True}]


async def test_fast_role_calls_carry_no_effort():
    fast = StubChat(replies=[SameClaimVerdict(same=True)])
    await _llm(fast=fast).check_support(["s1"], ["q1"])
    req = fast.requests[0]
    assert req.effort is None and req.role == "fast" and req.op == "check_support"
    assert "[0] s1" in req.content[0] and "- q1" in req.content[0]


async def test_web_evidence_researches_then_structures_with_the_fast_model():
    search = StubSearcher()
    evidence = WebEvidence(label="refuted", explanation="x", sources=[Source(url="https://a.org/x", quote="q")])
    fast = StubChat(replies=[evidence])
    outcome = await _llm(fast=fast, search=search).web_evidence("The claim")
    assert search.researched == [(search.researched[0][0], "The claim", 3)]
    assert "Report:\nREPORT" in fast.requests[0].content[0]
    assert fast.requests[0].op == "structure_web"
    assert outcome.evidence is evidence and outcome.returned_urls == {"https://a.org/x"}


def test_native_mode_requires_a_native_searcher():
    with pytest.raises(ValueError, match="server-side search"):
        GenericLLM(StubChat(), StubChat(), StubChat(), research_mode="native")


async def test_schema_fallback_parses_json_text_and_repairs_once():
    judge = StubChat(capabilities=Capabilities(supports_schema=False), replies=[
        ChatResponse(text="Sure! ```json\n{\"same\": tru}\n```"),
        ChatResponse(text=json.dumps({"same": True, "reason": "fixed"})),
    ])
    verdict = await _llm(judge=judge).same_claim("a", "b")
    assert verdict == SameClaimVerdict(same=True, reason="fixed")
    assert "JSON schema" in judge.requests[0].system and judge.requests[0].schema is None
    repair = judge.requests[1]
    assert repair.op == "same_claim:repair" and "rejected" in repair.content[-1]


async def test_schema_fallback_fails_after_the_repair_attempt():
    judge = StubChat(capabilities=Capabilities(supports_schema=False), replies=[
        ChatResponse(text="nope"), ChatResponse(text="still nope"),
    ])
    with pytest.raises(ValueError):
        await _llm(judge=judge).same_claim("a", "b")


async def test_native_schema_model_that_returns_text_gets_one_repair():
    judge = StubChat(replies=[ChatResponse(text="garbage"), ChatResponse(text='{"same": true}')])
    verdict = await _llm(judge=judge).same_claim("a", "b")
    assert verdict.same is True
    assert judge.requests[0].schema is SameClaimVerdict and judge.requests[1].op == "same_claim:repair"
