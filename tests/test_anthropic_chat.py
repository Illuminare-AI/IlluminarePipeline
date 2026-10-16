"""Request shape of the Anthropic adapter, with the SDK client stubbed out."""
from types import SimpleNamespace

import pytest

from factcheck.llm import telemetry
from factcheck.llm.chat import ChatRequest, ImagePart, ModelRefusal
from factcheck.llm.providers.anthropic import AnthropicChat
from factcheck.models import SameClaimVerdict


def _client(parse=None, create=None, beta_create=None):
    return SimpleNamespace(
        messages=SimpleNamespace(parse=parse, create=create),
        beta=SimpleNamespace(messages=SimpleNamespace(create=beta_create)),
    )


def _response(parsed=None, stop="end_turn", content=()):
    return SimpleNamespace(
        parsed_output=parsed, stop_reason=stop, content=list(content),
        usage=SimpleNamespace(input_tokens=12, output_tokens=3),
    )


async def test_parse_request_shape_and_telemetry():
    seen = {}

    async def parse(**kwargs):
        seen.update(kwargs)
        return _response(parsed=SameClaimVerdict(same=True))

    chat = AnthropicChat("claude-opus-5", client=_client(parse=parse))
    col, token = telemetry.activate()
    try:
        resp = await chat.complete(ChatRequest(
            system="sys", content=[ImagePart(b"img", "image/png"), "Claim A"], schema=SameClaimVerdict,
            effort="medium", role="judge", op="same_claim",
        ))
    finally:
        telemetry.deactivate(token)

    assert resp.parsed == SameClaimVerdict(same=True)
    assert seen["model"] == "claude-opus-5" and seen["output_format"] is SameClaimVerdict
    assert seen["output_config"] == {"effort": "medium"} and seen["system"] == "sys"
    blocks = seen["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[1] == {"type": "text", "text": "Claim A"}
    assert col.calls[0].op == "same_claim" and col.calls[0].input_tokens == 12
    assert col.calls[0].model == "claude-opus-5" and col.calls[0].role == "judge"


async def test_haiku_drops_effort_and_plain_text_uses_create():
    seen = {}

    async def create(**kwargs):
        seen.update(kwargs)
        return _response(content=[SimpleNamespace(type="text", text="hello")])

    chat = AnthropicChat("claude-haiku-4-5", client=_client(create=create))
    assert not chat.capabilities.supports_effort
    resp = await chat.complete(ChatRequest(system="s", content=["x"], effort="low"))
    assert "output_config" not in seen and resp.text == "hello"


async def test_refusal_raises():
    async def parse(**kwargs):
        return _response(stop="refusal")

    chat = AnthropicChat("claude-opus-5", client=_client(parse=parse))
    with pytest.raises(ModelRefusal):
        await chat.complete(ChatRequest(system="s", content=["x"], schema=SameClaimVerdict))


async def test_research_uses_the_search_tool_and_harvests_urls():
    seen = []

    async def beta_create(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return _response(stop="pause_turn", content=[
                SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://example.org/a")]),
            ])
        return _response(stop="end_turn", content=[
            SimpleNamespace(type="fallback"),
            SimpleNamespace(type="web_search_tool_result", content=SimpleNamespace(error="rate limit")),
            SimpleNamespace(type="text", text="report", citations=[SimpleNamespace(url="https://example.org/b")]),
        ])

    chat = AnthropicChat("claude-sonnet-5-5", client=_client(beta_create=beta_create))
    result = await chat.research("SYS", "The claim", max_uses=4)

    assert len(seen) == 2, "pause_turn must resume the loop"
    assert seen[0]["model"] == "claude-sonnet-5-5" and seen[0]["system"] == "SYS"
    assert seen[0]["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]
    assert seen[0]["output_config"] == {"effort": "low"}
    assert seen[0]["fallbacks"] == "default" and seen[0]["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen[1]["messages"][1]["role"] == "assistant"
    assert result.report == "report"
    assert result.returned_urls == {"https://example.org/a", "https://example.org/b"}
