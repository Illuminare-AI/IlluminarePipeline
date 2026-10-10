"""Stage 7: evaluate the claims of one post against each other.

Claims are researched concurrently and in isolation, so one claim's verdict can contradict
another's (one explanation says a movement is undocumented while the next claim cites five
outlets covering it). This stage shows the model every resolved claim at once and lets it
revise explanations, reuse a sibling claim's sources, and change labels, under code-enforced
rules so nothing the search did not find can be introduced:

- Only sources already attached to a sibling claim can be borrowed, matched by URL.
- `supported` and `refuted` still need two independent domains after borrowing.
- Claims settled by a published fact-check or by memory are context only; they are never changed.
- Revised explanations go back through the stage 6 self-check against the quoted passages.
"""
from __future__ import annotations

import re

from ..llm.base import LLM
from ..models import ClaimLabel, ClaimResult, ReconcileOutput, Source
from . import s6_assemble

PROTECTED_ORIGINS = frozenset({"fact_check_api", "memory"})


def _norm_url(u: str) -> str:
    return re.sub(r"[#?].*$", "", u.strip().lower().rstrip("/"))


def _domain(u: str) -> str:
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", _norm_url(u)).split("/")[0])


def _three_sentences(text: str) -> str:
    return " ".join(s6_assemble.split_sentences(text)[:3])


def apply_revisions(claims: list[ClaimResult], output: ReconcileOutput) -> list[ClaimResult]:
    """Pure merge of the model's revisions into the claims, enforcing the rules above."""
    revised = list(claims)
    for rev in output.revisions:
        if not 0 <= rev.claim_index < len(claims):
            continue
        current = revised[rev.claim_index]
        if current.evidence_origin in PROTECTED_ORIGINS:
            continue

        # Borrow sibling sources by URL; anything not already on the card is dropped.
        have = {_norm_url(s.url) for s in current.sources}
        pool: dict[str, Source] = {}
        for j, other in enumerate(claims):
            if j == rev.claim_index:
                continue
            for src in other.sources:
                pool.setdefault(_norm_url(src.url), src)
        borrowed = [pool[_norm_url(u)] for u in rev.borrow_sources if _norm_url(u) in pool and _norm_url(u) not in have]
        sources = list(current.sources) + borrowed

        label: ClaimLabel = current.label
        if rev.label is not None and rev.label != current.label:
            independent = {_domain(s.url) for s in sources}
            if rev.label in ("supported", "refuted") and len(independent) < 2:
                pass  # not enough evidence to move to a hard verdict; keep the original label
            else:
                label = rev.label

        explanation = current.explanation
        if rev.explanation is not None and rev.explanation.strip():
            explanation = _three_sentences(rev.explanation)

        if label == current.label and explanation == current.explanation and not borrowed:
            continue
        revised[rev.claim_index] = current.model_copy(
            update={"label": label, "explanation": explanation, "sources": sources}
        )
    return revised


async def reconcile(claims: list[ClaimResult], llm: LLM) -> list[ClaimResult]:
    output = await llm.reconcile_claims(claims)
    merged = apply_revisions(claims, output)
    results: list[ClaimResult] = []
    for before, after in zip(claims, merged):
        if after is before or after.explanation == before.explanation:
            results.append(after)
        else:
            results.append(await s6_assemble.self_check(after, llm))
    return results
