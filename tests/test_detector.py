import httpx
import pytest

from factcheck.services.detector import WALTERWRITES_IMAGE_DETECTION_URL, WalterWritesDetector

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make_detector(handler, **kwargs) -> WalterWritesDetector:
    return WalterWritesDetector(api_key="test-key", transport=httpx.MockTransport(handler), **kwargs)


async def test_request_shape_matches_walterwrites_spec():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-api-key")
        seen["content_type"] = request.headers.get("content-type")
        seen["body"] = request.content
        return httpx.Response(
            200,
            json={
                "prediction": "real",
                "confidence": 0.9964,
                "probabilities": {"real": 0.9964, "fake": 0.0013, "inpainting": 0.0022},
                "credits_charged": 6,
            },
        )

    signal = await make_detector(handler).score(PNG, "image/png")

    assert seen["url"] == WALTERWRITES_IMAGE_DETECTION_URL
    assert seen["api_key"] == "test-key"
    assert seen["content_type"].startswith("multipart/form-data")
    assert b'name="file"' in seen["body"]
    assert b'filename="image.png"' in seen["body"]
    assert b"Content-Type: image/png" in seen["body"]
    assert PNG in seen["body"]
    assert signal is not None and signal.provider == "walterwrites"
    assert signal.verdict == "real"
    assert signal.score == pytest.approx(0.0035)
    assert signal.threshold == 0.9


async def test_fake_and_inpainting_both_count_as_ai_signal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "prediction": "inpainting",
                "confidence": 0.6,
                "probabilities": {"real": 0.05, "fake": 0.35, "inpainting": 0.6},
            },
        )

    signal = await make_detector(handler).score(PNG, "image/png")
    assert signal is not None
    assert signal.verdict == "inpainting"
    assert signal.score == pytest.approx(0.95)


async def test_falls_back_to_real_probability_when_ai_classes_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prediction": "fake", "probabilities": {"real": 0.03}})

    signal = await make_detector(handler).score(PNG, "image/png")
    assert signal is not None and signal.score == pytest.approx(0.97)


async def test_falls_back_to_confidence_when_probabilities_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prediction": "fake", "confidence": 0.91})

    signal = await make_detector(handler).score(PNG, "image/png")
    assert signal is not None and signal.score == pytest.approx(0.91)

    def real_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"prediction": "real", "confidence": 0.91})

    signal = await make_detector(real_handler).score(PNG, "image/png")
    assert signal is not None and signal.score == pytest.approx(0.09)


async def test_unparseable_response_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"credits_charged": 6})

    assert await make_detector(handler).score(PNG, "image/png") is None


async def test_http_error_raises_so_stage_marks_detector_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "insufficient_credits", "detail": "balance too low"})

    with pytest.raises(httpx.HTTPStatusError):
        await make_detector(handler).score(PNG, "image/png")


async def test_unsupported_media_type_skips_without_calling_api():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call the API for SVG")

    assert await make_detector(handler).score(b"<svg/>", "image/svg+xml") is None


async def test_oversized_image_skips_without_calling_api():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call the API for a file over 10 MB")

    big = b"\x00" * (10 * 1024 * 1024 + 1)
    assert await make_detector(handler).score(big, "image/jpeg") is None
