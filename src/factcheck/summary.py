"""One-line verdict for the top of the card, derived in code from the per-claim results.

No model call: the headline is a deterministic function of the claim labels, the origin status
and the persuasion tags, so it is consistent, free, and never says more than the analysis below
it supports. The detailed cards remain the evidence; this is the glance view.
"""
from __future__ import annotations

from .models import Card, Summary

_TACTIC_FLAG = {
    "urgency": "Urgency cue",
    "authority": "Appeal to authority",
    "fear": "Fear cue",
    "promised_reward": "Promised reward",
}

_ORIGIN_FLAG = {
    "possible_ai_signal": "Possible AI image",
    "credentials_present": "Content Credentials present",
    "matched_reputable_source": "Image found on reputable sources",
}


def summarize(card: Card) -> Summary:
    labels = [c.label for c in card.claims]
    total = len(labels)
    refuted = labels.count("refuted")
    supported = labels.count("supported")
    context = labels.count("missing_context")
    unverified = labels.count("not_enough_evidence")
    claims_word = "claim" if total == 1 else "claims"

    if total == 0:
        extract = card.stages.get("extract")
        if extract is not None and extract.state in ("failed", "timeout"):
            verdict, headline = "nothing", "Could not be checked"
            detail = "Claim extraction did not complete, so no claims were checked."
        else:
            verdict, headline = "nothing", "Nothing to fact-check"
            detail = "No checkable factual claims were found in this post."
    elif refuted == total:
        verdict, headline = "false", "Likely false"
        detail = (
            "The claim is contradicted by independent sources."
            if total == 1
            else f"All {total} claims are contradicted by independent sources."
        )
    elif refuted:
        verdict, headline = "mixed", "Partly false"
        detail = f"{refuted} of {total} claims are contradicted by independent sources."
        if supported:
            detail += f" {supported} {'is' if supported == 1 else 'are'} supported."
    elif context:
        verdict, headline = "context", "Needs context"
        detail = (
            f"{context} of {total} claims {'is' if context == 1 else 'are'} true as stated but misleading without context."
            if total > 1
            else "The claim is true as stated but misleading without context."
        )
    elif supported == total:
        verdict, headline = "true", "Checks out"
        detail = (
            "The claim is supported by independent sources."
            if total == 1
            else f"All {total} claims are supported by independent sources."
        )
    elif supported:
        verdict, headline = "mixed", "Partly verified"
        detail = f"{supported} of {total} claims are supported; the rest could not be verified either way."
    else:
        verdict, headline = "unverified", "Unverified"
        detail = (
            f"No reliable evidence was found for or against the {claims_word}."
            if unverified == total
            else f"The {claims_word} could not be verified."
        )

    flags: list[str] = []
    origin_flag = _ORIGIN_FLAG.get(card.origin.status)
    if origin_flag:
        flags.append(origin_flag)
    for tag in card.persuasion:
        flag = _TACTIC_FLAG.get(tag.tactic)
        if flag and flag not in flags:
            flags.append(flag)
    if card.from_memory:
        flags.append("Reused a stored result")
    return Summary(verdict=verdict, headline=headline, detail=detail, flags=flags)  # type: ignore[arg-type]
