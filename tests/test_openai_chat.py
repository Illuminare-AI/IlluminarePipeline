"""Request shape of the OpenAI-compatible adapter, with the SDK client stubbed out."""
from types import SimpleNamespace

import pytest

from factcheck.llm import telemetry
from factcheck.llm.chat import ChatRequest, ImagePart, ModelRefusal
from factcheck.llm.providers.openai_compat import OpenAICompatChat
from factcheck.models import SameClaimVerdict


def _client(seen, content='{"same": true}', refusal=None, finish="stop"):
    async def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=refusal), finish_reason=finish)],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=4),
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


async def test_strict_schema_request_and_parsed_reply():
    seen = {}
    chat = OpenAICompatChat("gpt-5", _client(seen), effort_param="reasoning_effort", temperature=None,
                            max_tokens_param="max_completion_tokens")
    col, token = telemetry.activate()
    try:
        resp = await chat.complete(ChatRequest(
            system="sys", content=[ImagePart(b"img", "image/png"), "Claim A"], schema=SameClaimVerdict,
            effort="low", role="judge", op="same_claim", max_tokens=512,
        ))
    finally:
        telemetry.deactivate(token)
    assert resp.parsed == SameClaimVerdict(same=True) and resp.stop_reason == "stop"
    rf = seen["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert seen["reasoning_effort"] == "low" and "temperature" not in seen
    assert seen["max_completion_tokens"] == 512 and "max_tokens" not in seen
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    user = seen["messages"][1]["content"]
    assert user[0]["type"] == "image_url" and user[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user[1] == {"type": "text", "text": "Claim A"}
    assert col.calls[0].input_tokens == 20 and col.calls[0].provider == "openai"


async def test_json_schema_mode_is_not_strict_and_sets_temperature():
    seen = {}
    chat = OpenAICompatChat("gemma3:12b", _client(seen), provider="ollama", schema_mode="json_schema")
    await chat.complete(ChatRequest(system="s", content=["x"], schema=SameClaimVerdict, effort="low"))
    assert seen["response_format"]["json_schema"]["strict"] is False
    assert seen["temperature"] == 0.0 and "reasoning_effort" not in seen and seen["max_tokens"] == 4096


async def test_schema_mode_none_sends_no_response_format():
    seen = {}
    chat = OpenAICompatChat("kimi-k2", _client(seen), provider="kimi", schema_mode="none", supports_images=False)
    assert not chat.capabilities.supports_schema and not chat.capabilities.supports_images
    resp = await chat.complete(ChatRequest(system="s", content=["x"], schema=SameClaimVerdict))
    assert "response_format" not in seen and resp.parsed is None and resp.text == '{"same": true}'


async def test_invalid_json_leaves_parsed_empty_and_counts_a_parse_failure():
    chat = OpenAICompatChat("m", _client({}, content="not json"), schema_mode="json_schema")
    col, token = telemetry.activate()
    try:
        resp = await chat.complete(ChatRequest(system="s", content=["x"], schema=SameClaimVerdict))
    finally:
        telemetry.deactivate(token)
    assert resp.parsed is None and resp.text == "not json" and col.calls[0].parse_failures == 1


async def test_refusal_raises():
    chat = OpenAICompatChat("m", _client({}, content=None, refusal="no"))
    with pytest.raises(ModelRefusal):
        await chat.complete(ChatRequest(system="s", content=["x"]))
