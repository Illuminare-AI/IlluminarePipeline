"""Request shape of the stage 4 research call, with the SDK client stubbed out."""
from types import SimpleNamespace

from factcheck.llm.anthropic_llm import AnthropicLLM
from factcheck.models import WebEvidence


async def test_web_research_uses_the_search_model_and_search_cap():
    llm = AnthropicLLM(model="claude-opus-5", api_key="k", search_model="claude-sonnet-5-5", search_max_uses=4)
    seen = {}

    async def fake_create(**kwargs):
        seen.update(kwargs)
        result = SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://example.org/a")])
        text = SimpleNamespace(type="text", text="report", citations=[SimpleNamespace(url="https://example.org/b")])
        fallback = SimpleNamespace(type="fallback")
        return SimpleNamespace(content=[fallback, result, text], stop_reason="end_turn")

    async def fake_parse(system, content, output_format, **kwargs):
        seen["structured_with"] = kwargs.get("model")
        return WebEvidence(label="not_enough_evidence", explanation="x")

    llm.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    llm._parse = fake_parse  # type: ignore[method-assign]

    outcome = await llm.web_evidence("The claim")

    assert seen["model"] == "claude-sonnet-5-5"
    assert seen["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]
    assert seen["output_config"] == {"effort": "low"}
    assert seen["fallbacks"] == "default"
    assert seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen["structured_with"] == "claude-haiku-4-5"
    assert outcome.returned_urls == {"https://example.org/a", "https://example.org/b"}
