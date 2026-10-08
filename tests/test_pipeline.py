import asyncio

from factcheck.llm.base import WebSearchOutcome
from factcheck.llm.fake import source
from factcheck.models import Post, WebEvidence
from factcheck.pipeline import check
from factcheck.services.detector import StaticDetector
from factcheck.services.factcheck_api import ClaimReview, StaticFactCheckClient
from tests.conftest import make_image

CLAIM = "The Eiffel Tower was sold for scrap in 2024."


async def test_nothing_checkable(deps):
    card = await check(Post(caption="lol what a day?"), deps)
    assert card.nothing_checkable
    assert card.stages["web"].state == "skipped"
    assert card.origin.status == "unavailable"  # no image


async def test_fact_check_match_skips_web(deps):
    deps.factcheck = StaticFactCheckClient(
        {"eiffel": [ClaimReview(claim_text=CLAIM, publisher="Snopes", url="https://snopes.com/x", rating="False")]}
    )
    card = await check(Post(caption=CLAIM), deps)
    assert card.claims[0].label == "refuted"
    assert card.claims[0].evidence_origin == "fact_check_api"
    assert card.stages["web"].state == "skipped"
    assert "web_evidence" not in deps.llm.calls


async def test_web_evidence_validation_drops_hallucinated_urls(deps):
    deps.llm.set_web_result(
        "eiffel",
        WebSearchOutcome(
            evidence=WebEvidence(
                label="refuted",
                explanation="The tower still stands in Paris. Nobody sold it.",
                sources=[
                    source("https://a.example/1", "The tower still stands"),
                    source("https://b.example/2", "The tower remains in Paris"),
                    source("https://made-up.example/", "fabricated"),
                ],
                disputed_spans=["sold for scrap", "not in caption"],
            ),
            returned_urls={"https://a.example/1", "https://b.example/2"},
        ),
    )
    card = await check(Post(caption=CLAIM), deps)
    c = card.claims[0]
    assert c.label == "refuted"
    assert [s.url for s in c.sources] == ["https://a.example/1", "https://b.example/2"]
    assert c.disputed_spans == ["sold for scrap"]


async def test_refuted_needs_two_independent_sources(deps):
    deps.llm.set_web_result(
        "eiffel",
        WebSearchOutcome(
            evidence=WebEvidence(
                label="refuted",
                explanation="The tower still stands.",
                sources=[source("https://a.example/1", "still stands"), source("https://a.example/2", "stands")],
            ),
            returned_urls={"https://a.example/1", "https://a.example/2"},
        ),
    )
    card = await check(Post(caption=CLAIM), deps)
    assert card.claims[0].label == "not_enough_evidence"


async def test_self_check_drops_unsupported_sentence(deps):
    deps.llm.set_web_result(
        "eiffel",
        WebSearchOutcome(
            evidence=WebEvidence(
                label="refuted",
                explanation="The tower still stands. Aliens built it in 1889.",
                sources=[source("https://a.example/", "tower still stands"), source("https://b.example/", "stands today")],
            ),
            returned_urls={"https://a.example/", "https://b.example/"},
        ),
    )
    card = await check(Post(caption=CLAIM), deps)
    assert card.claims[0].explanation == "The tower still stands."


async def test_memory_hit_on_recompressed_image(deps):
    img = make_image(seed=3, size=(256, 256))
    caption = "Share before it's deleted! " + CLAIM
    first = await check(Post(image=img, caption=caption), deps)
    assert not first.from_memory
    assert any(t.tactic == "urgency" for t in first.persuasion)

    recompressed = make_image(seed=3, size=(200, 200), fmt="JPEG", quality=40)
    second = await check(Post(image=recompressed, caption=caption + "  "), deps)
    assert second.from_memory
    assert second.claims == first.claims
    assert second.check_id != first.check_id


async def test_claim_memory_requires_same_claim(deps):
    deps.llm.set_web_result(
        "rose",
        WebSearchOutcome(
            evidence=WebEvidence(label="supported", explanation="Prices rose.", sources=[
                source("https://a.example/", "prices rose 5%"), source("https://b.example/", "rose 5 percent")]),
            returned_urls={"https://a.example/", "https://b.example/"},
        ),
    )
    await check(Post(caption="Egg prices rose 5% in March 2025."), deps)
    card = await check(Post(caption="Egg prices fell 5% in March 2025."), deps)
    assert card.claims[0].evidence_origin != "memory"


async def test_origin_never_changes_label(deps):
    deps.detector = StaticDetector(score=0.99)
    deps.llm.set_web_result("eiffel", WebSearchOutcome(
        evidence=WebEvidence(label="not_enough_evidence", explanation="No evidence found."), returned_urls=set()))
    card = await check(Post(image=make_image(5), caption=CLAIM), deps)
    assert card.origin.status == "possible_ai_signal"
    assert card.claims[0].label == "not_enough_evidence"


async def test_no_signal_is_not_verified(deps):
    deps.detector = StaticDetector(score=0.2)
    card = await check(Post(image=make_image(6), caption="nice view"), deps)
    assert card.origin.status == "no_signal_found"
    assert "not verification" in card.origin.note


async def test_stage_timeout_degrades(deps):
    async def slow(*a, **k):
        await asyncio.sleep(10)

    deps.llm.extract = slow
    deps.settings.stage_timeout = 0.05
    card = await check(Post(caption=CLAIM), deps)
    assert card.stages["extract"].state == "timeout"
    assert card.stages["web"].state == "skipped"
    assert card.check_id


async def test_stage_exception_degrades(deps):
    async def boom(*a, **k):
        raise RuntimeError("provider down")

    deps.llm.web_evidence = boom
    card = await check(Post(caption=CLAIM), deps)
    assert card.stages["web"].state == "failed"
    assert card.claims[0].label == "not_enough_evidence"


async def test_replay_mode_serves_saved_card(deps):
    post = Post(caption=CLAIM)
    first = await check(post, deps)
    deps.settings.replay_mode = True
    deps.llm.calls.clear()
    again = await check(post, deps)
    assert again.check_id == first.check_id
    assert "replay" in again.stages
    assert deps.llm.calls == []
