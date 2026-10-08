import json

import httpx
import pytest

from factcheck.services.detector import WINSTON_IMAGE_DETECTION_URL, WinstonDetector

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make_detector(handler, **kwargs) -> WinstonDetector:
    return WinstonDetector(api_key="test-key", transport=httpx.MockTransport(handler), **kwargs)


async def test_request_shape_matches_winston_spec():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ai_probability": 0.12, "human_probability": 0.88, "score": 88})

    det = make_detector(handler, version="5")
    signal = await det.score(PNG, "image/png")

    assert seen["url"] == WINSTON_IMAGE_DETECTION_URL
    assert seen["auth"] == "Bearer test-key"
    assert seen["content_type"].startswith("application/json")
    assert seen["body"]["image"].startswith("data:image/png;base64,")
    assert seen["body"]["version"] == "5"
    assert signal is not None and signal.provider == "winston-ai"
    assert signal.score == pytest.approx(0.12)
    assert signal.threshold == 0.9


async def test_version_omitted_when_unset():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ai_probability": 0.5})

    await make_detector(handler).score(PNG, "image/png")
    assert "version" not in seen["body"]


async def test_falls_back_to_human_score_when_ai_probability_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"score": 3})  # 3% human => 0.97 AI

    signal = await make_detector(handler).score(PNG, "image/png")
    assert signal is not None and signal.score == pytest.approx(0.97)


async def test_unparseable_response_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"version": "5"})

    assert await make_detector(handler).score(PNG, "image/png") is None


async def test_http_error_raises_so_stage_marks_detector_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "PAYMENT_REQUIRED", "description": "no credits"})

    with pytest.raises(httpx.HTTPStatusError):
        await make_detector(handler).score(PNG, "image/png")


async def test_unsupported_media_type_skips_without_calling_api():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call the API for GIF")

    assert await make_detector(handler).score(b"GIF89a", "image/gif") is None
