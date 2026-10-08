"""Orchestration: check(post) -> Card.

Order: 0 -> 1 -> 2 -> (3 and 5 together) -> 4 if needed -> 6.
Every stage runs through run_stage, so a failure or timeout marks the stage and the card still returns.
"""
from __future__ import annotations

import asyncio
import uuid

from .deps import Deps
from .models import Card, ClaimResult, OriginResult, Post
from .stages import (
    s0_fingerprint,
    s1_extract,
    s2_memory,
    s3_factcheck,
    s4_web,
    s5_origin,
    s6_assemble,
)
from .stages.runner import run_stage, skipped
from .trace import Tracer, load_replay


async def check(post: Post, deps: Deps) -> Card:
    s = deps.settings
    check_id = uuid.uuid4().hex[:12]
    tracer = Tracer(check_id, s.trace_dir)
    card = Card(check_id=check_id)

    if s.replay_mode:
        replayed = load_replay(s.trace_dir, post)
        if replayed is not None:
            return replayed

    if not post.image and not (post.caption or "").strip():
        card.stages["input"] = skipped("empty post")
        return card

    # Stage 0: fingerprint and media memory
    fp, st = await run_stage("fingerprint", s0_fingerprint.fingerprint(post, deps.store), s.stage_timeout)
    card.stages["fingerprint"] = st
    tracer.record("fingerprint", input={"caption": post.caption}, output=fp, error=st.detail)
    phash = fp.phash if fp else None
    if fp and fp.media_match:
        stored = fp.media_match.card
        card = stored.model_copy(
            update={"check_id": check_id, "from_memory": True, "stages": {**stored.stages, "fingerprint": st}}
        )
        tracer.flush(card, post)
        return card

    # Stage 1: extract
    ex, st = await run_stage("extract", s1_extract.extract(post, deps.llm), s.stage_timeout)
    card.stages["extract"] = st
    tracer.record("extract", input={"caption": post.caption}, output=ex, error=st.detail)

    # Stage 5 starts now so it overlaps with everything claim-related
    origin_task = asyncio.create_task(
        run_stage(
            "origin",
            s5_origin.origin_signals(post.image, deps.credentials, deps.detector, s.detector_threshold),
            s.stage_timeout,
        )
    )

    if ex is None:
        card.stages["memory"] = skipped("extraction failed")
        card.stages["fact_check"] = skipped("extraction failed")
        card.stages["web"] = skipped("extraction failed")
        card.stages["self_check"] = skipped("extraction failed")
    else:
        card.extraction = ex
        card.persuasion = ex.persuasion
        if not ex.claims:
            for name in ("memory", "fact_check", "web", "self_check"):
                card.stages[name] = skipped("nothing checkable")
        else:
            card.claims = await _resolve_claims(ex.claims, post, ex.ocr_text, deps, card, tracer)

    origin, st = await origin_task
    card.stages["origin"] = st
    card.origin = origin or OriginResult(status="unavailable", note=st.detail or "origin stage failed")
    tracer.record("origin", output=card.origin, error=st.detail)

    try:
        await deps.store.save(post, card, phash)
        card.stages["save"] = _ok()
    except Exception as exc:  # noqa: BLE001
        card.stages["save"] = skipped(f"save failed: {exc}")
    tracer.flush(card, post)
    return card


def _ok():
    from .models import StageStatus

    return StageStatus(state="ok", ms=0)


async def _resolve_claims(claims, post, ocr_text, deps, card, tracer) -> list[ClaimResult]:
    s = deps.settings
    results: list[ClaimResult] = []
    stage_states = {"memory": [], "fact_check": [], "web": [], "self_check": []}

    for claim in claims:
        # Stage 2: memory
        mem, st = await run_stage("memory", s2_memory.memory_match(claim, deps.store, deps.llm), s.stage_timeout)
        stage_states["memory"].append(st)
        tracer.record("memory", input=claim, output=mem, error=st.detail)
        if mem:
            results.append(mem)
            stage_states["fact_check"].append(skipped("memory hit"))
            stage_states["web"].append(skipped("memory hit"))
            stage_states["self_check"].append(skipped("memory hit"))
            continue

        # Stage 3: existing fact-checks
        fc, st = await run_stage(
            "fact_check", s3_factcheck.existing_fact_checks(claim, deps.factcheck, deps.llm), s.stage_timeout
        )
        stage_states["fact_check"].append(st)
        tracer.record("fact_check", input=claim, output=fc, error=st.detail)
        if fc:
            results.append(fc)
            stage_states["web"].append(skipped("fact-check match"))
            stage_states["self_check"].append(skipped("fact-check explanation is templated"))
            continue

        # Stage 4: web evidence
        web, st = await run_stage(
            "web", s4_web.web_evidence(claim, deps.llm, post.caption, ocr_text), s.web_stage_timeout
        )
        stage_states["web"].append(st)
        tracer.record("web", input=claim, output=web, error=st.detail)
        if web is None:
            results.append(
                ClaimResult(
                    claim=claim,
                    label="not_enough_evidence",
                    explanation="The evidence search did not complete.",
                    evidence_origin="none",
                )
            )
            stage_states["self_check"].append(skipped("no web result"))
            continue

        # Stage 6: self-check
        checked, st = await run_stage("self_check", s6_assemble.self_check(web, deps.llm), s.stage_timeout)
        stage_states["self_check"].append(st)
        tracer.record("self_check", input=web.explanation, output=checked, error=st.detail)
        results.append(checked or web.model_copy(update={"explanation": ""}))

    for name, states in stage_states.items():
        card.stages[name] = _merge(states)
    return results


def _merge(states):
    """Collapse per-claim statuses into one: worst state wins, timings summed."""
    from .models import StageStatus

    if not states:
        return skipped("no claims")
    order = {"failed": 3, "timeout": 2, "ok": 1, "skipped": 0}
    worst = max(states, key=lambda st: order[st.state])
    return StageStatus(state=worst.state, ms=sum(st.ms for st in states), detail=worst.detail)
