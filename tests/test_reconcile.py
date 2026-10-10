import pytest

from factcheck.llm.base import WebSearchOutcome
from factcheck.llm.fake import FakeLLM, source
from factcheck.models import (
    ClaimResult,
    ClaimRevision,
    ExtractionOutput,
    Post,
    ReconcileOutput,
    WebEvidence,
)
from factcheck.pipeline import check
from factcheck.stages.s7_reconcile import apply_revisions, reconcile

GLOBE = source("https://www.theglobeandmail.com/a", "The Cockroach movement grew out of exam-leak anger.", publisher="Globe")
PBS = source("https://www.pbs.org/b", "Cockroach protests expose cracks in the government.", publisher="PBS")


def arrest() -> ClaimResult:
    return ClaimResult(
        claim="Police arrested Abhijeet Dipke, leader of the Cockroach movement.",
        label="not_enough_evidence",
        explanation="No sources verify the existence of the Cockroach movement or the arrest.",
        evidence_origin="web",
    )


def movement() -> ClaimResult:
    return ClaimResult(
        claim="The Cockroach movement emerged from exam scandals.",
        label="supported",
        explanation="The movement grew out of exam-leak anger.",
        sources=[GLOBE, PBS],
        evidence_origin="web",
    )


def test_revision_rewrites_explanation_and_borrows_sibling_sources():
    out = ReconcileOutput(revisions=[ClaimRevision(
        claim_index=0,
        explanation="The Cockroach movement itself is documented. The arrest of Abhijeet Dipke is not covered by any source.",
        borrow_sources=["https://www.theglobeandmail.com/a", "https://www.pbs.org/b"],
    )])
    revised = apply_revisions([arrest(), movement()], out)
    assert revised[0].explanation.startswith("The Cockroach movement itself is documented.")
    assert [s.url for s in revised[0].sources] == [GLOBE.url, PBS.url]
    assert revised[0].label == "not_enough_evidence"
    assert revised[1] == movement()


def test_only_urls_already_on_the_card_can_be_borrowed():
    out = ReconcileOutput(revisions=[ClaimRevision(
        claim_index=0, borrow_sources=["https://made-up.example/x", "https://www.pbs.org/b?utm=1"],
    )])
    revised = apply_revisions([arrest(), movement()], out)
    assert [s.url for s in revised[0].sources] == [PBS.url]


def test_hard_verdict_needs_two_independent_domains():
    claims = [arrest(), movement().model_copy(update={"sources": [GLOBE]})]
    out = ReconcileOutput(revisions=[ClaimRevision(claim_index=0, label="refuted", borrow_sources=[GLOBE.url])])
    assert apply_revisions(claims, out)[0].label == "not_enough_evidence"

    out = ReconcileOutput(revisions=[ClaimRevision(claim_index=0, label="refuted", borrow_sources=[GLOBE.url, PBS.url])])
    assert apply_revisions([arrest(), movement()], out)[0].label == "refuted"


def test_soft_labels_change_without_extra_sources():
    out = ReconcileOutput(revisions=[ClaimRevision(claim_index=0, label="missing_context")])
    assert apply_revisions([arrest(), movement()], out)[0].label == "missing_context"


def test_fact_check_and_memory_results_are_never_changed():
    settled = movement().model_copy(update={"evidence_origin": "fact_check_api"})
    remembered = movement().model_copy(update={"evidence_origin": "memory"})
    out = ReconcileOutput(revisions=[
        ClaimRevision(claim_index=0, label="refuted", explanation="changed"),
        ClaimRevision(claim_index=1, label="refuted", explanation="changed"),
        ClaimRevision(claim_index=7, label="refuted"),
    ])
    revised = apply_revisions([settled, remembered], out)
    assert revised == [settled, remembered]


def test_explanation_is_capped_at_three_sentences():
    out = ReconcileOutput(revisions=[ClaimRevision(claim_index=0, explanation="One. Two. Three. Four.")])
    assert apply_revisions([arrest(), movement()], out)[0].explanation == "One. Two. Three."


async def test_rewritten_explanation_goes_through_self_check():
    llm = FakeLLM()
    llm.reconcile_output = ReconcileOutput(revisions=[ClaimRevision(
        claim_index=0,
        explanation="The Cockroach movement is documented. Dipke was seen on Mars yesterday.",
        borrow_sources=[GLOBE.url, PBS.url],
    )])
    revised = await reconcile([arrest(), movement()], llm)
    assert revised[0].explanation == "The Cockroach movement is documented."
    assert "check_support" in llm.calls


class _TwoClaimLLM(FakeLLM):
    async def extract(self, image, media_type, caption, ocr_text):
        return ExtractionOutput(claims=[c.strip() for c in (caption or "").split("|") if c.strip()])


async def test_pipeline_runs_consistency_stage_for_multiple_claims(deps):
    llm = _TwoClaimLLM()
    llm.set_web_result("emerged", WebSearchOutcome(
        evidence=WebEvidence(label="supported", explanation="The movement grew out of exam-leak anger.", sources=[GLOBE, PBS]),
        returned_urls={GLOBE.url, PBS.url},
    ))
    llm.reconcile_output = ReconcileOutput(revisions=[ClaimRevision(
        claim_index=0,
        explanation="The Cockroach movement is documented. There is no evidence of the arrest.",
        borrow_sources=[GLOBE.url],
    )])
    deps.llm = llm
    card = await check(Post(caption=f"{arrest().claim} | {movement().claim}"), deps)
    assert card.stages["consistency"].state == "ok"
    assert card.claims[0].explanation == "The Cockroach movement is documented. There is no evidence of the arrest."
    assert [s.url for s in card.claims[0].sources] == [GLOBE.url]
    assert card.claims[1].label == "supported"


async def test_pipeline_skips_consistency_stage_for_single_claim(deps):
    card = await check(Post(caption="Egg prices rose 5% in March 2024."), deps)
    assert card.stages["consistency"].state == "skipped"
    assert "reconcile_claims" not in deps.llm.calls


async def test_consistency_failure_keeps_per_claim_results(deps):
    llm = _TwoClaimLLM()

    async def boom(claims):
        raise RuntimeError("model down")

    llm.reconcile_claims = boom
    deps.llm = llm
    card = await check(Post(caption="Egg prices rose 5% in 2024. | Milk prices fell 2% in 2024."), deps)
    assert card.stages["consistency"].state == "failed"
    assert len(card.claims) == 2
    assert all(c.label == "not_enough_evidence" for c in card.claims)


@pytest.mark.parametrize("n", [0, 1])
def test_apply_revisions_is_a_no_op_without_revisions(n):
    claims = [arrest(), movement()][: n + 1]
    assert apply_revisions(claims, ReconcileOutput()) == claims
