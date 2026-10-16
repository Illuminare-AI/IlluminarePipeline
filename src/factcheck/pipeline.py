"""Orchestration: check(post) -> Card.

Order: 0 -> 1 -> 2 -> (3, 4 and 5 together; 4 is cancelled on a stage 3 hit) -> 6 -> 7.
Claims are resolved concurrently, then stage 7 reviews them together for consistency.
Every stage runs through run_stage, so a failure or timeout marks the stage and the card still returns.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

from .config import Settings
from .deps import Deps
from .llm import telemetry
from .models import Card, ClaimResult, OriginResult, Post, StageStatus
from .services.ocr import read_image_context, read_image_text
from .stages import (
    s0_fingerprint,
    s1_extract,
    s2_memory,
    s3_factcheck,
    s4_web,
    s5_origin,
    s6_assemble,
    s7_reconcile,
)
from .stages.runner import run_stage, skipped
from .summary import summarize
from .trace import Tracer, load_replay


def run_meta(s: Settings) -> dict:
    """Which backend and models a check ran on. Goes into trace.json and /health."""
    live = s.live
    return {
        "backend": s.llm_backend,
        "models": {
            "judge": s.llm_model if live else "fake",
            "fast": s.llm_fast_model if live else "fake",
            "search": s.llm_search_model if live else "fake",
        },
        "research_mode": s.research_mode if live else "fake",
    }


async def check(post: Post, deps: Deps) -> Card:
    """Run one check with its own telemetry collector, so per-call records land in its trace."""
    _, token = telemetry.activate()
    try:
        return await _check(post, deps)
    finally:
        telemetry.deactivate(token)


async def _check(post: Post, deps: Deps) -> Card:
    s = deps.settings
    request_post = post
    check_id = uuid.uuid4().hex[:12]
    tracer = Tracer(check_id, s.trace_dir, meta=run_meta(s))
    card = Card(check_id=check_id, analysis_mode="fake" if s.llm_backend == "fake" else "live")

    if s.replay_mode:
        replayed = load_replay(s.trace_dir, post)
        if replayed is not None:
            replayed = replayed.model_copy(update={"analysis_mode": "replay"})
            replayed.summary = summarize(replayed)
            return replayed

    if not post.image and not (post.caption or "").strip() and not (post.ocr_text or "").strip():
        card.stages["input"] = skipped("empty post")
        card.summary = summarize(card)
        return card

    if post.image and s.image_vision_enabled and post.describe_image and s.image_context_url:
        context, st = await run_stage(
            "image_context", read_image_context(post, s), s.image_context_timeout,
        )
        card.stages["image_context"] = st
        card.image_context = context
        if context is not None:
            card.stages["vision"] = StageStatus(
                state="ok" if context.vision_status == "ok" else
                "skipped" if context.vision_status == "disabled" else "failed",
                detail="Local image descriptions disabled" if context.vision_status == "disabled" else
                "Local image model unavailable" if context.vision_status == "unavailable" else None,
            )
            card.stages["ocr"] = skipped("text supplied") if post.ocr_text else StageStatus(
                state="ok" if context.ocr_status == "ok" else "failed",
                detail=None if context.ocr_status == "ok" else "Image text extraction unavailable",
            )
            if not (post.ocr_text or "").strip():
                text = context.ocr_text if context.ocr_status == "ok" else ""
                if not text and context.observations is not None:
                    text = "\n".join(context.observations.additional_visible_text)
                post = post.model_copy(update={"ocr_text": text or None})
        else:
            card.stages["vision"] = st
            card.stages["ocr"] = skipped("text supplied") if post.ocr_text else st
        tracer.record("image_context", output=context, error=st.detail)
    elif post.image and not (post.ocr_text or "").strip() and s.image_context_url:
        text, st = await run_stage("ocr", read_image_text(post, s), s.ocr_timeout)
        card.stages["ocr"] = st
        if text is not None:
            post = post.model_copy(update={"ocr_text": text})
        tracer.record("ocr", output=text, error=st.detail)
        if s.image_vision_enabled and not post.describe_image:
            card.stages["vision"] = skipped("description not requested")
    else:
        card.stages["ocr"] = skipped(
            "text supplied" if post.ocr_text else
            "OCR service not configured" if post.image else "no image"
        )
        if post.image and s.image_vision_enabled:
            card.stages["vision"] = skipped(
                "description not requested" if not post.describe_image else "Image service not configured"
            )

    # Stage 0: fingerprint and media memory
    fp, st = await run_stage("fingerprint", s0_fingerprint.fingerprint(post, deps.store), s.stage_timeout)
    card.stages["fingerprint"] = st
    tracer.record("fingerprint", input={"caption": post.caption}, output=fp, error=st.detail)
    phash = fp.phash if fp else None
    if fp and fp.media_match:
        stored = fp.media_match.card
        card = stored.model_copy(
            update={"check_id": check_id, "from_memory": True,
                    "image_context": card.image_context,
                    "stages": {**stored.stages, **card.stages, "fingerprint": st}}
        )
        if card.extraction and card.image_context and card.image_context.observations:
            card.extraction = card.extraction.model_copy(update={
                "image_description": card.image_context.observations.description,
            })
        card.summary = summarize(card)
        tracer.flush(card, request_post)
        return card

    # Stage 1: extract. A text-only judge model gets the local image description in place of the image.
    description = (
        card.image_context.observations.description
        if card.image_context and card.image_context.observations else None
    )
    ex, st = await run_stage(
        "extract", s1_extract.extract(post, deps.llm, image_description=description), s.stage_timeout
    )
    card.stages["extract"] = st
    tracer.record(
        "extract", input={"caption": post.caption, "ocr_text": post.ocr_text}, output=ex, error=st.detail
    )

    # Stage 5 starts now so it overlaps with everything claim-related
    origin_task = asyncio.create_task(
        run_stage(
            "origin",
            s5_origin.origin_signals(
                post.image, deps.credentials, deps.detector, s.detector_threshold, deps.reverse_image
            ),
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
        if card.image_context and card.image_context.observations:
            card.extraction.image_description = card.image_context.observations.description
        card.persuasion = ex.persuasion
        if not ex.claims:
            for name in ("memory", "fact_check", "web", "self_check", "consistency"):
                card.stages[name] = skipped("nothing checkable")
        else:
            card.claims = await _resolve_claims(ex.claims, post, ex.ocr_text, deps, card, tracer)
            card.claims = await _reconcile_claims(card.claims, deps, card, tracer)

    origin, st = await origin_task
    card.stages["origin"] = st
    card.origin = origin or OriginResult(status="unavailable", note=st.detail or "origin stage failed")
    tracer.record("origin", output=card.origin, error=st.detail)

    try:
        await deps.store.save(post, card, phash)
        card.stages["save"] = _ok()
    except Exception as exc:  # noqa: BLE001
        card.stages["save"] = skipped(f"save failed: {exc}")
    card.summary = summarize(card)
    tracer.flush(card, request_post)
    return card


def _ok():
    from .models import StageStatus

    return StageStatus(state="ok", ms=0)


async def _reconcile_claims(claims, deps, card, tracer) -> list[ClaimResult]:
    """Stage 7: review all claims together. On failure the per-claim results stand."""
    if len(claims) < 2:
        card.stages["consistency"] = skipped("single claim")
        return claims
    if all(c.evidence_origin in s7_reconcile.PROTECTED_ORIGINS for c in claims):
        card.stages["consistency"] = skipped("all claims settled by fact-checks or memory")
        return claims
    revised, st = await run_stage(
        "consistency", s7_reconcile.reconcile(claims, deps.llm), deps.settings.stage_timeout
    )
    card.stages["consistency"] = st
    tracer.record("consistency", input=claims, output=revised, error=st.detail)
    return revised or claims


async def _resolve_claims(claims, post, ocr_text, deps, card, tracer) -> list[ClaimResult]:
    """Resolve every claim concurrently; the stage takes as long as the slowest claim."""
    outcomes = await asyncio.gather(
        *(_resolve_claim(claim, post, ocr_text, deps, tracer) for claim in claims)
    )
    stage_states: dict[str, list] = {"memory": [], "fact_check": [], "web": [], "self_check": []}
    results: list[ClaimResult] = []
    for result, states in outcomes:
        results.append(result)
        for name, st in states.items():
            stage_states[name].append(st)
    for name, states in stage_states.items():
        card.stages[name] = _merge(states)
    return results


async def _resolve_claim(claim, post, ocr_text, deps, tracer) -> tuple[ClaimResult, dict]:
    """Stages 2 -> 3 -> 4 -> 6 for one claim. Returns the result and each stage's status.

    The web search (stage 4) starts speculatively alongside the fact-check lookup (stage 3)
    and is cancelled if a published fact-check matches. This trades a little wasted search
    spend on fact-check hits for a shorter wall clock on misses, which are the common case.
    """
    s = deps.settings
    states: dict = {}

    # Stage 2: memory
    mem, st = await run_stage("memory", s2_memory.memory_match(claim, deps.store, deps.llm), s.stage_timeout)
    states["memory"] = st
    tracer.record("memory", input=claim, output=mem, error=st.detail)
    if mem:
        states["fact_check"] = skipped("memory hit")
        states["web"] = skipped("memory hit")
        states["self_check"] = skipped("memory hit")
        return mem, states

    # Stage 4 starts now; stage 3 runs in the foreground
    async def search_web():
        # Construct the coroutine inside the task, so early cancellation cannot leak it.
        return await run_stage(
            "web", s4_web.web_evidence(claim, deps.llm, post.caption, ocr_text),
            s.web_stage_timeout,
        )

    web_task = asyncio.create_task(search_web())

    # Stage 3: existing fact-checks
    fc, st = await run_stage(
        "fact_check", s3_factcheck.existing_fact_checks(claim, deps.factcheck, deps.llm), s.stage_timeout
    )
    states["fact_check"] = st
    tracer.record("fact_check", input=claim, output=fc, error=st.detail)
    if fc:
        web_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await web_task
        states["web"] = skipped("fact-check match")
        states["self_check"] = skipped("fact-check explanation is templated")
        return fc, states

    # Stage 4: web evidence
    web, st = await web_task
    states["web"] = st
    tracer.record("web", input=claim, output=web, error=st.detail)
    if web is None:
        states["self_check"] = skipped("no web result")
        return (
            ClaimResult(
                claim=claim,
                label="not_enough_evidence",
                explanation="The evidence search did not complete.",
                evidence_origin="none",
            ),
            states,
        )

    # Stage 6: self-check
    checked, st = await run_stage("self_check", s6_assemble.self_check(web, deps.llm), s.stage_timeout)
    states["self_check"] = st
    tracer.record("self_check", input=web.explanation, output=checked, error=st.detail)
    return checked or web.model_copy(update={"explanation": ""}), states


def _merge(states):
    """Collapse per-claim statuses into one: worst state wins, timings summed."""
    from .models import StageStatus

    if not states:
        return skipped("no claims")
    order = {"failed": 3, "timeout": 2, "ok": 1, "skipped": 0}
    worst = max(states, key=lambda st: order[st.state])
    return StageStatus(state=worst.state, ms=sum(st.ms for st in states), detail=worst.detail)
