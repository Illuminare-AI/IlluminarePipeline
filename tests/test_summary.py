from factcheck.models import Card, ClaimResult, OriginResult, StageStatus, Tactic
from factcheck.summary import summarize


def claim(label: str) -> ClaimResult:
    return ClaimResult(claim="x", label=label, evidence_origin="web")  # type: ignore[arg-type]


def card(*labels: str, **kwargs) -> Card:
    return Card(check_id="t", claims=[claim(label) for label in labels], **kwargs)


def test_no_claims_is_nothing_to_check():
    s = summarize(card())
    assert (s.verdict, s.headline) == ("nothing", "Nothing to fact-check")
    failed = summarize(card(stages={"extract": StageStatus(state="timeout", ms=1, detail="t")}))
    assert failed.headline == "Could not be checked"


def test_refuted_claims_win():
    assert summarize(card("refuted")).headline == "Likely false"
    s = summarize(card("refuted", "supported", "not_enough_evidence"))
    assert (s.verdict, s.headline) == ("mixed", "Partly false")
    assert s.detail == "1 of 3 claims are contradicted by independent sources. 1 is supported."


def test_context_then_supported_then_unverified():
    assert summarize(card("missing_context", "supported")).headline == "Needs context"
    assert summarize(card("supported", "supported")).headline == "Checks out"
    assert summarize(card("supported", "not_enough_evidence")).headline == "Partly verified"
    s = summarize(card("not_enough_evidence"))
    assert (s.verdict, s.headline) == ("unverified", "Unverified")
    assert s.detail == "No reliable evidence was found for or against the claim."


def test_flags_collect_origin_persuasion_and_memory():
    s = summarize(card(
        "supported",
        origin=OriginResult(status="possible_ai_signal"),
        persuasion=[Tactic(tactic="urgency", phrase="now"), Tactic(tactic="urgency", phrase="again"), Tactic(tactic="fear", phrase="deadly")],
        from_memory=True,
    ))
    assert s.flags == ["Possible AI image", "Urgency cue", "Fear cue", "Reused a stored result"]
