"""Run every case in eval/cases.jsonl through the pipeline and print a results table.

    python eval/run_eval.py                 # uses LLM_BACKEND from .env (fake by default)
    LLM_BACKEND=anthropic python eval/run_eval.py

Fields per case: id, caption, image (path relative to eval/), expected_label (label of the first
claim, or null for "nothing checkable"), expected_origin, expected_tactics, must_not_accuse.
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
        if label != case.get("expected_label"):
            problems.append(f"label {label} != {case.get('expected_label')}")
        if case.get("expected_origin") and card.origin.status != case["expected_origin"]:
            problems.append(f"origin {card.origin.status} != {case['expected_origin']}")
        got_tactics = {t.tactic for t in card.persuasion}
        if set(case.get("expected_tactics", [])) - got_tactics:
            problems.append(f"tactics {sorted(got_tactics)}")
        if case.get("must_not_accuse") and card.origin.status == "possible_ai_signal":
            problems.append("FALSE ACCUSATION")
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
