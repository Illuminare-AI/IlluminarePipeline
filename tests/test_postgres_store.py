import hashlib
import os
import uuid
import pytest
from sqlalchemy import text
from factcheck.config import load_settings
from factcheck.models import Card, ClaimResult, DetectorSignal, OriginResult, Post, Source, Tactic

URL = os.environ.get("POSTGRES_URL") or load_settings().postgres_url
pytestmark = pytest.mark.skipif(not URL, reason="POSTGRES_URL not set")
CLAIM = "Drinking seawater cures dehydration in desert hikers"
OTHER = "Penguins can legally vote in Antarctic elections"
_encoder = None


def _shared_encoder():
    global _encoder
    if _encoder is None:
        from factcheck.store.postgres import SentenceEmbeddingEncoder

        _encoder = SentenceEmbeddingEncoder()
    return _encoder


def _card(claim: str, *, origin_note="", evidence="web", persuasion=()) -> Card:
    return Card(
        check_id="test_" + uuid.uuid4().hex[:8],
        claims=[
            ClaimResult(
                claim=claim,
                label="refuted",
                explanation=f"explanation {origin_note}",
                sources=[Source(url="https://example.org/a", title="A", publisher="P")],
                disputed_spans=["cures dehydration"],
                evidence_origin=evidence,
            )
        ],
        persuasion=list(persuasion),
    )


async def _wipe(store):
    async with store.session_factory() as s, s.begin():
        await s.execute(text("""
            DELETE FROM claims c
            WHERE EXISTS (SELECT 1 FROM verdicts v WHERE v.claim_id = c.id AND left(v.check_id, 5) = 'test_')
              AND NOT EXISTS (SELECT 1 FROM verdicts v WHERE v.claim_id = c.id AND left(v.check_id, 5) <> 'test_')
        """))
        await s.execute(text("DELETE FROM verdicts WHERE left(check_id, 5) = 'test_'"))
        await s.execute(text("DELETE FROM media WHERE left(check_id, 5) = 'test_'"))


@pytest.fixture
async def store():
    from factcheck.store.postgres import PostgresStore

    s = PostgresStore(db_url=URL, phash_max_distance=10, encoder=_shared_encoder())
    await s.init_db()
    await s.init_db()
    await _wipe(s)
    yield s
    await _wipe(s)
    await s.engine.dispose()


async def _scalar(store, sql, **params):
    async with store.session_factory() as s:
        return (await s.execute(text(sql), params)).scalar_one()


async def test_semantic_recall_and_unrelated_claim(store):
    a, b = _card(CLAIM), _card(OTHER)
    await store.save(Post(caption="a"), a, None)
    await store.save(Post(caption="b"), b, None)

    hits = await store.find_claims("Can desert hikers cure dehydration by drinking sea water?", k=3)
    assert hits and hits[0].check_id == a.check_id
    got = hits[0].card.claims[0]
    assert got.claim == CLAIM and got.label == "refuted" and got.evidence_origin == "web"
    assert got.sources[0].url == "https://example.org/a" and got.disputed_spans == ["cures dehydration"]


async def test_same_claim_is_one_row_with_history_and_prefers_evidence(store):
    first = _card("  " + CLAIM.upper() + "  ", origin_note="one")
    second = _card(CLAIM, origin_note="two")
    empty = _card(CLAIM, evidence="none")
    await store.save(Post(caption="x"), first, None)
    first_seen = await _scalar(store, "SELECT first_seen FROM claims WHERE claim_norm = :n", n=CLAIM.lower())
    await store.save(Post(caption="x"), second, None)
    await store.save(Post(caption="x"), empty, None)

    assert await _scalar(store, "SELECT count(*) FROM claims WHERE claim_norm = :n", n=CLAIM.lower()) == 1
    assert await _scalar(store, "SELECT count(*) FROM verdicts WHERE left(check_id,5)='test_'") == 3
    assert await _scalar(store, "SELECT first_seen FROM claims WHERE claim_norm = :n", n=CLAIM.lower()) == first_seen

    hits = await store.find_claims(CLAIM, k=1)
    assert hits[0].check_id == second.check_id


async def test_media_roundtrip_origin_persuasion_caption_and_file_hash(store):
    img = b"not-really-an-image"
    card = _card(CLAIM, persuasion=[Tactic(tactic="urgency", phrase="Share before it's deleted")])
    card.origin = OriginResult(
        status="possible_ai_signal",
        note="detector flagged",
        detector=DetectorSignal(provider="hive", score=0.97, threshold=0.9),
    )
    await store.save(Post(image=img, caption="look!"), card, "ffff0000ffff0000")

    near = await store.find_media("ffff0000ffff0001")
    assert [h.check_id for h in near] == [card.check_id]
    hit = near[0]
    assert hit.caption == "look!" and hit.phash == "ffff0000ffff0000"
    assert hit.card.origin.status == "possible_ai_signal" and hit.card.origin.detector.score == 0.97
    assert hit.card.persuasion[0].tactic == "urgency"
    assert hit.card.claims[0].claim == CLAIM

    assert await store.find_media("0000ffff0000ffff") == []
    stored = await _scalar(store, "SELECT file_hash FROM media WHERE check_id = :c", c=card.check_id)
    assert stored == hashlib.sha256(img).hexdigest()
    linked = await _scalar(
        store,
        "SELECT count(*) FROM media_claims mc JOIN media m ON m.id = mc.media_id WHERE m.check_id = :c",
        c=card.check_id,
    )
    assert linked == 1


async def test_check_with_no_claims_keeps_persuasion(store):
    card = Card(check_id="test_" + uuid.uuid4().hex[:8], persuasion=[Tactic(tactic="fear", phrase="they are coming")])
    await store.save(Post(image=b"x", caption="boo"), card, "aaaa0000aaaa0000")
    hit = (await store.find_media("aaaa0000aaaa0000"))[0]
    assert hit.card.claims == [] and hit.card.persuasion[0].phrase == "they are coming"


async def test_full_text_search(store):
    card = _card(CLAIM)
    await store.save(Post(caption="a"), card, None)
    hits = await store.find_claims_by_keyword("desert hikers dehydration")
    assert card.check_id in {h.check_id for h in hits}
    assert await store.find_claims_by_keyword("zzzznotaword") == []


async def test_saving_same_check_twice_does_not_duplicate(store):
    card = _card(CLAIM)
    await store.save(Post(image=b"y", caption="a"), card, "bbbb0000bbbb0000")
    await store.save(Post(image=b"y", caption="a"), card, "bbbb0000bbbb0000")
    assert await _scalar(store, "SELECT count(*) FROM verdicts WHERE check_id = :c", c=card.check_id) == 1
    assert await _scalar(store, "SELECT count(*) FROM media WHERE check_id = :c", c=card.check_id) == 1
