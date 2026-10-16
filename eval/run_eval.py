"""Benchmark harness: run eval/cases.jsonl through the pipeline, score each case, summarise.

    python eval/run_eval.py                              # LLM_BACKEND from .env (fake by default)
    LLM_BACKEND=anthropic python eval/run_eval.py --repeat 3 --out eval/results.jsonl
    python eval/run_eval.py --model anthropic:claude-sonnet-5-5 --label sonnet
    python eval/run_eval.py --models openai:gpt-5,kimi:kimi-k2 --search-model anthropic:claude-sonnet-5-5
    python eval/run_eval.py --ids false-urgent,moon-landing

--models runs the whole case set once per spec, with that spec in every role a role flag does not
pin. With research mode "native" the search role must stay an Anthropic model, so pin it with
--search-model when comparing other providers.

One JSONL line per case run goes to --out (appended, so a model matrix accumulates in one file),
with the run label, the models, the score and the timings. The printed summary has accuracy,
the source hallucination rate, self-check drops, p50/p95 per stage and token totals.

Case fields: id, caption, ocr_text, image (path relative to eval/), expected_label (label of the
first claim; null for "nothing checkable"; or a list of acceptable labels), expected_claims
(statements that must appear among the extracted claims, matched fuzzily), expected_origin,
expected_tactics, must_not_accuse, forbidden_claim_terms (case-insensitive substrings no
extracted claim may contain, used to catch claims about the post itself).

Label and claim scoring only count against the live backend: the fake backend extracts by rule
and knows no facts, so on it they are reported but never fail the run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from factcheck.config import Settings
from factcheck.deps import build_deps
from factcheck.models import Card, Post
from factcheck.pipeline import check, run_meta
from factcheck.trace import load_trace

HERE = Path(__file__).parent
CLAIM_MATCH_THRESHOLD = 0.55


# ---------- scoring ----------


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def claim_similarity(a: str, b: str) -> float:
    """Blend of character similarity and token overlap, so a rewrite with the same entities
    and numbers still matches."""
    na, nb = _norm(a), _norm(b)
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return max(SequenceMatcher(None, na, nb).ratio(), jaccard)


def claims_matched(expected: list[str], got: list[str]) -> list[bool]:
    return [any(claim_similarity(e, g) >= CLAIM_MATCH_THRESHOLD for g in got) for e in expected]


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s])


def score_case(case: dict, card: Card, trace: dict | None, live: bool) -> dict[str, Any]:
    """Pure: compare one card (and its trace) with the case expectations."""
    label = card.claims[0].label if card.claims else None
    expected = case.get("expected_label")
    acceptable = expected if isinstance(expected, list) else [expected]
    label_ok = label in acceptable

    got_claims = [c.claim for c in card.claims]
    matched = claims_matched(case.get("expected_claims", []), got_claims)
    claims_ok = all(matched)

    problems: list[str] = []
    soft: list[str] = []  # reported, not failing (fake backend)
    (problems if live else soft).append(f"label {label} != {expected}") if not label_ok else None
    if not claims_ok:
        missing = [e for e, ok in zip(case.get("expected_claims", []), matched) if not ok]
        (problems if live else soft).append(f"missing claim {missing[0]!r}")
    if case.get("expected_origin") and card.origin.status != case["expected_origin"]:
        problems.append(f"origin {card.origin.status} != {case['expected_origin']}")
    got_tactics = {t.tactic for t in card.persuasion}
    if set(case.get("expected_tactics", [])) - got_tactics:
        problems.append(f"tactics {sorted(got_tactics)}")
    if case.get("must_not_accuse") and card.origin.status == "possible_ai_signal":
        problems.append("FALSE ACCUSATION")
    forbidden = [t.lower() for t in case.get("forbidden_claim_terms", [])]
    bad = [c for c in got_claims if any(t in c.lower() for t in forbidden)]
    if bad:
        problems.append(f"claim about the medium: {bad[0]!r}")
    failed = {k: v.state for k, v in card.stages.items() if v.state in ("failed", "timeout")}
    if failed:
        problems.append(f"stages {failed}")

    calls = (trace or {}).get("calls", [])
    marks = (trace or {}).get("marks", [])
    proposed = sum(m.get("proposed", 0) for m in marks if m.get("kind") == "web_sources")
    kept = sum(m.get("kept", 0) for m in marks if m.get("kind") == "web_sources")
    sc_in = sc_out = 0
    for ev in (trace or {}).get("events", []):
        if ev.get("stage") == "self_check" and ev.get("output"):
            sc_in += _sentences(ev.get("input") or "")
            sc_out += _sentences((ev["output"] or {}).get("explanation", ""))

    return {
        "label": label,
        "expected_label": expected,
        "label_ok": label_ok,
        "claims": got_claims,
        "claims_ok": claims_ok,
        "origin": card.origin.status,
        "tactics": sorted(got_tactics),
        "problems": problems,
        "soft_problems": soft,
        "ok": not problems,
        "stages": {k: {"state": v.state, "ms": v.ms} for k, v in card.stages.items()},
        "calls": len(calls),
        "calls_by_role": _by_role(calls),
        "errors": sum(1 for c in calls if c.get("error")),
        "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
        "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
        "sources_proposed": proposed,
        "sources_kept": kept,
        "self_check_sentences_in": sc_in,
        "self_check_sentences_out": sc_out,
    }


def _by_role(calls: list[dict]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for role in ("judge", "fast", "search"):
        lat = [c["latency_ms"] for c in calls if c.get("role") == role]
        if lat:
            out[role] = {"n": len(lat), "p50_ms": percentile(lat, 50), "max_ms": max(lat)}
    return out


def percentile(values: list[int | float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Aggregate scored rows (one model/run label) into the ranking metrics."""
    n = len(rows)
    if n == 0:
        return {}
    scored_labels = [r for r in rows if r.get("live")]
    wall = [r["wall_ms"] for r in rows]
    stage_ms: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        for name, st in r["stages"].items():
            if st["state"] == "ok" and st["ms"]:
                stage_ms[name].append(st["ms"])
    proposed = sum(r["sources_proposed"] for r in rows)
    kept = sum(r["sources_kept"] for r in rows)
    sc_in = sum(r["self_check_sentences_in"] for r in rows)
    sc_out = sum(r["self_check_sentences_out"] for r in rows)
    return {
        "runs": n,
        "passed": sum(r["ok"] for r in rows),
        "label_accuracy": _rate(sum(r["label_ok"] for r in scored_labels), len(scored_labels)),
        "claims_match_rate": _rate(sum(r["claims_ok"] for r in scored_labels), len(scored_labels)),
        "source_hallucination_rate": _rate(proposed - kept, proposed),
        "self_check_drop_rate": _rate(sc_in - sc_out, sc_in),
        "call_errors": sum(r["errors"] for r in rows),
        "calls_per_check": round(sum(r["calls"] for r in rows) / n, 1),
        "tokens_per_check": round(sum(r["input_tokens"] + r["output_tokens"] for r in rows) / n),
        "wall_p50_ms": percentile(wall, 50),
        "wall_p95_ms": percentile(wall, 95),
        "stages": {
            name: {"n": len(v), "p50_ms": percentile(v, 50), "p95_ms": percentile(v, 95)}
            for name, v in sorted(stage_ms.items())
        },
    }


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


# ---------- running ----------


def load_cases(path: Path, ids: set[str] | None) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [c for c in cases if not ids or c["id"] in ids]


def settings_for(args: argparse.Namespace, spec: str | None = None) -> Settings:
    """Settings for one run: .env plus the CLI overrides. `spec` fills every role not pinned."""
    overrides: dict[str, Any] = {"replay_mode": False}  # replay would serve the first model's cards
    if args.backend:
        overrides["llm_backend"] = args.backend
    for key, value in (("llm_model", args.model), ("llm_fast_model", args.fast_model),
                       ("llm_search_model", args.search_model)):
        if value:
            overrides[key] = value
        elif spec:
            overrides[key] = spec
    if spec and "llm_backend" not in overrides:
        overrides["llm_backend"] = "live"
    return Settings(**overrides)


async def run_one(settings: Settings, cases: list[dict], label: str, args: argparse.Namespace) -> list[dict]:
    deps = build_deps(settings)
    init_db = getattr(deps.store, "init_db", None)
    if init_db is not None:
        await init_db()
    meta = run_meta(settings)
    live = settings.live
    rows: list[dict] = []
    width = max(len(c["id"]) for c in cases)
    for rep in range(args.repeat):
        for case in cases:
            image = (HERE / case["image"]).read_bytes() if case.get("image") else None
            post = Post(image=image, caption=case.get("caption"), ocr_text=case.get("ocr_text"))
            start = time.perf_counter()
            card = await check(post, deps)
            wall_ms = int((time.perf_counter() - start) * 1000)
            trace = load_trace(settings.trace_dir, card.check_id)
            row = {
                "case": case["id"], "run": label, "repeat": rep, "live": live, **meta,
                "check_id": card.check_id, "wall_ms": wall_ms,
                **score_case(case, card, trace, live),
            }
            rows.append(row)
            if args.out:  # append per case so an interrupted run keeps what finished
                with open(args.out, "a") as out:  # noqa: ASYNC230  (CLI script, nothing else runs)
                    out.write(json.dumps(row) + "\n")
            status = "; ".join(row["problems"]) or "ok"
            if row["soft_problems"]:
                status += f"  (unscored: {'; '.join(row['soft_problems'])})"
            timings = " ".join(f"{k}={v['ms']}ms" for k, v in row["stages"].items() if v["state"] == "ok" and v["ms"])
            print(f"{case['id']:<{width}}  {row['label']!s:<22} {row['origin']:<20} {status}\n{'':<{width}}  {timings}")

    summary = summarize(rows)
    print(f"\nrun={label} backend={settings.llm_backend} models={meta['models']} research={meta['research_mode']}")
    print(f"{summary['passed']}/{summary['runs']} case runs passed")
    for key in ("label_accuracy", "claims_match_rate", "source_hallucination_rate", "self_check_drop_rate",
                "call_errors", "calls_per_check", "tokens_per_check", "wall_p50_ms", "wall_p95_ms"):
        print(f"  {key:<26} {summary[key]}")
    for name, st in summary["stages"].items():
        print(f"  {name:<26} p50={st['p50_ms']}ms p95={st['p95_ms']}ms (n={st['n']})")
    return rows


async def run(args: argparse.Namespace) -> int:
    cases = load_cases(HERE / args.cases, set(args.ids.split(",")) if args.ids else None)
    specs = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else [None]
    all_rows: list[dict] = []
    for spec in specs:
        settings = settings_for(args, spec)
        meta = run_meta(settings)
        label = args.label or spec or ("fake" if not settings.live else "+".join(sorted(set(meta["models"].values()))))
        try:
            rows = await run_one(settings, cases, label, args)
        except ValueError as exc:  # a spec the registry or research mode cannot serve
            print(f"\nrun={label} skipped: {exc}")
            continue
        all_rows.extend(rows)
        print()
    if len(specs) > 1:
        print(f"{'run':<34} {'pass':>6} {'label_acc':>10} {'halluc':>8} {'wall_p50':>10} {'tokens':>8}")
        for spec in specs:
            rows = [r for r in all_rows if r["run"] == (args.label or spec)]
            if rows:
                sm = summarize(rows)
                print(f"{spec:<34} {sm['passed']:>3}/{sm['runs']:<2} {sm['label_accuracy']!s:>10} "
                      f"{sm['source_hallucination_rate']!s:>8} {sm['wall_p50_ms']:>10} {sm['tokens_per_check']:>8}")
    if not all_rows:
        return 1
    return 0 if all(r["ok"] for r in all_rows) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the eval cases and score them.")
    p.add_argument("--cases", default="cases.jsonl", help="case file, relative to eval/")
    p.add_argument("--ids", help="comma-separated case ids to run")
    p.add_argument("--repeat", type=int, default=1, help="run every case this many times")
    p.add_argument("--out", help="append one JSON line per case run to this file")
    p.add_argument("--label", help="run label written to --out (default: the model names)")
    p.add_argument("--backend", choices=["live", "anthropic", "fake"], help="override LLM_BACKEND")
    p.add_argument("--models", help="comma-separated model specs; the case set runs once per spec")
    p.add_argument("--model", help="override LLM_MODEL (judge role)")
    p.add_argument("--fast-model", help="override LLM_FAST_MODEL")
    p.add_argument("--search-model", help="override LLM_SEARCH_MODEL")
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
