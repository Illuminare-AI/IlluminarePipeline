from factcheck.models import Credentials, ImageMatch
from factcheck.services.c2pa import StaticCredentialsReader
from factcheck.services.detector import StaticDetector
from factcheck.services.reverse_image import StaticReverseImageSearch
from factcheck.stages.s5_origin import origin_signals
from tests.conftest import make_image

IMAGE = make_image(3)
REUTERS = ImageMatch(url="https://www.reuters.com/world/story", domain="reuters.com", title="Reuters story", kind="full")
COMMONS = ImageMatch(url="https://commons.wikimedia.org/wiki/File:A.jpg", domain="commons.wikimedia.org", kind="partial")


async def test_reputable_matches_give_their_own_status():
    result = await origin_signals(
        IMAGE, StaticCredentialsReader(None), StaticDetector(0.1), 0.9, StaticReverseImageSearch([REUTERS, COMMONS])
    )
    assert result.status == "matched_reputable_source"
    assert result.matches == [REUTERS, COMMONS]
    assert "2 reputable sites: reuters.com, commons.wikimedia.org" in result.note
    assert "original context" in result.note
    assert result.detector is not None and result.detector.score == 0.1


async def test_detector_hit_outranks_a_match_but_the_match_is_still_reported():
    result = await origin_signals(
        IMAGE, StaticCredentialsReader(None), StaticDetector(0.95), 0.9, StaticReverseImageSearch([REUTERS])
    )
    assert result.status == "possible_ai_signal"
    assert result.matches == [REUTERS]
    assert "also appears on 1 reputable site: reuters.com" in result.note
    assert "does not rule out a generated image" in result.note


async def test_credentials_outrank_everything():
    result = await origin_signals(
        IMAGE, StaticCredentialsReader(Credentials(issuer="Adobe")), StaticDetector(0.95), 0.9,
        StaticReverseImageSearch([REUTERS]),
    )
    assert result.status == "credentials_present"
    assert result.matches == [REUTERS]


async def test_partial_only_matches_say_so():
    result = await origin_signals(
        IMAGE, StaticCredentialsReader(None), StaticDetector(None), 0.9, StaticReverseImageSearch([COMMONS])
    )
    assert result.note.startswith("Part of this image also appears on 1 reputable site")


async def test_search_failure_or_absence_leaves_the_old_behaviour():
    failed = await origin_signals(
        IMAGE, StaticCredentialsReader(None), StaticDetector(0.1), 0.9,
        StaticReverseImageSearch(None, error=RuntimeError("quota")),
    )
    assert failed.status == "no_signal_found"
    assert failed.matches == []
    assert "reverse image search was not available" in failed.note

    unconfigured = await origin_signals(IMAGE, StaticCredentialsReader(None), StaticDetector(0.1), 0.9, None)
    assert unconfigured.status == "no_signal_found"
    assert "reverse image search" not in unconfigured.note

    empty = await origin_signals(IMAGE, StaticCredentialsReader(None), StaticDetector(0.1), 0.9, StaticReverseImageSearch([]))
    assert empty.status == "no_signal_found"
    assert "reverse image search" not in empty.note
