"""Run every case in eval/cases.jsonl through the pipeline and print a results table.

    python eval/run_eval.py                 # uses LLM_BACKEND from .env (fake by default)
    LLM_BACKEND=anthropic python eval/run_eval.py

Fields per case: id, caption, ocr_text, image (path relative to eval/), expected_label (label of the
first claim, null for "nothing checkable", or a list of acceptable labels so one case can hold for
both the fake and the live backend), expected_origin, expected_tactics, must_not_accuse,
forbidden_claim_terms (case-insensitive substrings that no extracted claim may contain, used to
catch claims about the post itself such as its timestamp or view count).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from factcheck.deps import build_deps
from factcheck.models import Post
from factcheck.pipeline import check

HERE = Path(__file__).parent


async def main() -> int:
    deps = build_deps()
    # Same warm-up the API does at startup: create the schema and load the embedding model
    # before any timed stage runs, so a cold store does not show up as a memory timeout.
    init_db = getattr(deps.store, "init_db", None)
    if init_db is not None:
        await init_db()
    failures = 0
    rows = []
    for line in (HERE / "cases.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        image = (HERE / case["image"]).read_bytes() if case.get("image") else None
        post = Post(image=image, caption=case.get("caption"), ocr_text=case.get("ocr_text"))
        card = await check(post, deps)
        label = card.claims[0].label if card.claims else None
        problems = []
        expected = case.get("expected_label")
        acceptable = expected if isinstance(expected, list) else [expected]
        if label not in acceptable:
            problems.append(f"label {label} != {expected}")
        if case.get("expected_origin") and card.origin.status != case["expected_origin"]:
            problems.append(f"origin {card.origin.status} != {case['expected_origin']}")
        got_tactics = {t.tactic for t in card.persuasion}
        if set(case.get("expected_tactics", [])) - got_tactics:
            problems.append(f"tactics {sorted(got_tactics)}")
        if case.get("must_not_accuse") and card.origin.status == "possible_ai_signal":
            problems.append("FALSE ACCUSATION")
        forbidden = [t.lower() for t in case.get("forbidden_claim_terms", [])]
        bad_claims = [c.claim for c in card.claims if any(t in c.claim.lower() for t in forbidden)]
        if bad_claims:
            problems.append(f"claim about the medium: {bad_claims[0]!r}")
        failed = {k: v.state for k, v in card.stages.items() if v.state in ("failed", "timeout")}
        if failed:
            problems.append(f"stages {failed}")
        timings = " ".join(f"{k}={v.ms}ms" for k, v in card.stages.items() if v.state == "ok")
        rows.append((case["id"], label, card.origin.status, "; ".join(problems) or "ok", timings))
        failures += bool(problems)
    width = max(len(r[0]) for r in rows)
    for cid, label, origin, status, timings in rows:
        print(f"{cid:<{width}}  {label!s:<22} {origin:<20} {status}\n{'':<{width}}  {timings}")
    print(f"\n{len(rows) - failures}/{len(rows)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
