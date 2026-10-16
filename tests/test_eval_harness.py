"""Scoring and aggregation in eval/run_eval.py, without running the pipeline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import run_eval

from factcheck.models import Card, ClaimResult, StageStatus


def _card(label="refuted", claims=("The Great Wall of China is visible from the Moon with the naked eye",)):
    return Card(
        check_id="abc",
        claims=[ClaimResult(claim=c, label=label, evidence_origin="web") for c in claims],
        stages={"extract": StageStatus(state="ok", ms=100), "web": StageStatus(state="ok", ms=2000)},
    )


def test_claim_matching_tolerates_rewrites():
    assert run_eval.claims_matched(
        ["The Great Wall of China is visible from the Moon"],
        ["The Great Wall of China can be seen from the Moon with the naked eye."],
    ) == [True]
    assert run_eval.claims_matched(["Water boils at 100 degrees"], ["Napoleon was short"]) == [False]


def test_score_case_live_counts_label_and_claims():
    case = {"id": "x", "expected_label": "refuted", "expected_claims": ["The Great Wall is visible from the Moon"]}
    trace = {
        "calls": [
            {"role": "judge", "op": "extract", "latency_ms": 100, "input_tokens": 10, "output_tokens": 5, "error": None},
            {"role": "search", "op": "web_evidence", "latency_ms": 900, "input_tokens": 1, "output_tokens": 1, "error": None},
        ],
        "marks": [{"kind": "web_sources", "proposed": 3, "kept": 2}],
        "events": [{"stage": "self_check", "input": "One. Two. Three.", "output": {"explanation": "One. Two."}}],
    }
    row = run_eval.score_case(case, _card(), trace, live=True)
    assert row["ok"] and row["label_ok"] and row["claims_ok"]
    assert row["calls"] == 2 and row["input_tokens"] == 11 and row["output_tokens"] == 6
    assert row["sources_proposed"] == 3 and row["sources_kept"] == 2
    assert row["self_check_sentences_in"] == 3 and row["self_check_sentences_out"] == 2
    assert row["calls_by_role"]["search"]["n"] == 1

    wrong = run_eval.score_case({"id": "x", "expected_label": "supported"}, _card(), trace, live=True)
    assert not wrong["ok"] and wrong["problems"] == ["label refuted != supported"]


def test_score_case_fake_backend_reports_label_without_failing():
    row = run_eval.score_case({"id": "x", "expected_label": "supported"}, _card(), None, live=False)
    assert row["ok"] and row["soft_problems"] == ["label refuted != supported"]


def test_score_case_hard_rules_apply_to_every_backend():
    card = _card(claims=("The post had 417K views",))
    row = run_eval.score_case({"id": "x", "forbidden_claim_terms": ["views"]}, card, None, live=False)
    assert not row["ok"] and "claim about the medium" in row["problems"][0]


def test_summarize_aggregates_rates_and_percentiles():
    base = {
        "live": True, "ok": True, "label_ok": True, "claims_ok": True, "errors": 0, "calls": 4,
        "input_tokens": 100, "output_tokens": 50, "sources_proposed": 4, "sources_kept": 3,
        "self_check_sentences_in": 4, "self_check_sentences_out": 4,
        "stages": {"web": {"state": "ok", "ms": 1000}},
    }
    rows = [
        {**base, "wall_ms": 1000},
        {**base, "wall_ms": 3000, "label_ok": False, "ok": False, "stages": {"web": {"state": "ok", "ms": 3000}}},
    ]
    s = run_eval.summarize(rows)
    assert s["runs"] == 2 and s["passed"] == 1
    assert s["label_accuracy"] == 0.5 and s["claims_match_rate"] == 1.0
    assert s["source_hallucination_rate"] == 0.25 and s["self_check_drop_rate"] == 0.0
    assert s["wall_p50_ms"] == 2000 and s["tokens_per_check"] == 150
    assert s["stages"]["web"]["p50_ms"] == 2000


def test_percentile():
    assert run_eval.percentile([], 50) == 0.0
    assert run_eval.percentile([5], 95) == 5
    assert run_eval.percentile([1, 2, 3, 4], 50) == 2.5


def test_settings_for_fills_unpinned_roles_from_the_matrix_spec():
    args = run_eval.parse_args(["--models", "openai:gpt-5,kimi:kimi-k2", "--search-model", "anthropic:claude-sonnet-5-5"])
    s = run_eval.settings_for(args, "openai:gpt-5")
    assert s.llm_model == "openai:gpt-5" and s.llm_fast_model == "openai:gpt-5"
    assert s.llm_search_model == "anthropic:claude-sonnet-5-5"
    assert s.live and not s.replay_mode
    plain = run_eval.settings_for(run_eval.parse_args(["--backend", "fake"]))
    assert not plain.live
