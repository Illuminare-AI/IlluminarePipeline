"""Per-call telemetry: records land in the trace of the check that made them."""
import asyncio

from factcheck.llm import telemetry
from factcheck.llm.base import WebSearchOutcome
from factcheck.llm.fake import source
from factcheck.models import Post, WebEvidence
from factcheck.pipeline import check, run_meta


def _trace(settings, card):
    from factcheck.trace import load_trace

    return load_trace(settings.trace_dir, card.check_id)


async def test_fake_calls_are_recorded_in_the_trace(deps, settings):
    deps.llm.set_web_result("eiffel", WebSearchOutcome(
        evidence=WebEvidence(
            label="refuted",
            explanation="It was not sold. The tower still stands in Paris.",
            sources=[source("https://a.org/x", "The tower still stands in Paris"),
                     source("https://b.org/y", "It was not sold"),
                     source("https://c.org/z", "never returned by search")],
        ),
        returned_urls={"https://a.org/x", "https://b.org/y"},
    ))
    card = await check(Post(caption="The Eiffel Tower was sold for scrap in 2024."), deps)
    trace = _trace(settings, card)

    assert trace["backend"] == "fake"
    assert trace["models"] == {"judge": "fake", "fast": "fake", "search": "fake"}
    ops = [c["op"] for c in trace["calls"]]
    assert ops[0] == "extract" and "web_evidence" in ops and "check_support" in ops
    assert all(c["provider"] == "fake" and c["error"] is None for c in trace["calls"])
    roles = {c["op"]: c["role"] for c in trace["calls"]}
    assert roles["web_evidence"] == "search" and roles["check_support"] == "fast"
    marks = [m for m in trace["marks"] if m["kind"] == "web_sources"]
    assert marks == [{
        "kind": "web_sources", "claim": "The Eiffel Tower was sold for scrap in 2024.",
        "proposed": 3, "kept": 2, "returned_urls": 2,
        "label_proposed": "refuted", "label_kept": "refuted",
    }]


async def test_concurrent_checks_keep_separate_collectors(deps, settings):
    cards = await asyncio.gather(
        check(Post(caption="Water boils at 100 degrees."), deps),
        check(Post(caption="The Moon is made of cheese."), deps),
    )
    traces = [_trace(settings, c) for c in cards]
    for trace in traces:
        assert [c["op"] for c in trace["calls"]].count("extract") == 1
    assert traces[0]["check_id"] != traces[1]["check_id"]


async def test_no_collector_is_a_noop():
    telemetry.record_call(telemetry.CallRecord("x", "m", "judge", "op", 1))
    telemetry.mark("anything", value=1)
    assert telemetry.current() is None


async def test_timed_call_records_errors():
    col, token = telemetry.activate()
    try:
        try:
            with telemetry.timed_call("p", "m", "judge", "op"):
                raise ValueError("boom")
        except ValueError:
            pass
    finally:
        telemetry.deactivate(token)
    assert col.calls[0].error == "ValueError: boom"
    assert col.calls[0].latency_ms >= 0


def test_run_meta_reports_models_for_live_backend():
    from factcheck.config import Settings

    s = Settings(llm_backend="anthropic", llm_model="a", llm_fast_model="b", llm_search_model="c", _env_file=None)
    assert run_meta(s) == {
        "backend": "anthropic", "models": {"judge": "a", "fast": "b", "search": "c"}, "research_mode": "native",
    }
