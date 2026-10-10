import base64
import json

import httpx
import pytest

from factcheck.services.reverse_image import (
    GOOGLE_VISION_ANNOTATE_URL,
    GoogleVisionReverseImageSearch,
    is_trusted,
    parse_trusted_domains,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def make_search(handler, **kwargs) -> GoogleVisionReverseImageSearch:
    return GoogleVisionReverseImageSearch(api_key="test-key", transport=httpx.MockTransport(handler), **kwargs)


def vision_response(web: dict) -> httpx.Response:
    return httpx.Response(200, json={"responses": [{"webDetection": web}]})


async def test_request_shape_matches_vision_spec():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return vision_response({})

    assert await make_search(handler).find(PNG, "image/png") == []
    assert seen["url"] == GOOGLE_VISION_ANNOTATE_URL
    assert seen["key"] == "test-key"
    req = seen["body"]["requests"][0]
    assert req["features"] == [{"type": "WEB_DETECTION", "maxResults": 20}]
    assert base64.b64decode(req["image"]["content"]) == PNG


async def test_only_trusted_domains_are_kept_and_titles_are_cleaned():
    def handler(request: httpx.Request) -> httpx.Response:
        return vision_response({
            "pagesWithMatchingImages": [
                {"url": "https://www.reuters.com/world/story", "pageTitle": "Reuters <b>story</b>  title", "fullMatchingImages": [{"url": "x"}]},
                {"url": "https://content-farm.example/repost", "pageTitle": "Repost", "fullMatchingImages": [{"url": "x"}]},
                {"url": "https://factcheck.afp.com/doc.123", "pageTitle": "AFP fact check", "partialMatchingImages": [{"url": "y"}]},
                {"url": "https://www.reuters.com/world/story?utm=1", "pageTitle": "duplicate"},
            ],
            "fullMatchingImages": [{"url": "https://upload.wikimedia.org/wikipedia/commons/a.jpg"}],
            "partialMatchingImages": [{"url": "https://i.redd.it/abc.jpg"}],
            "visuallySimilarImages": [{"url": "https://www.bbc.co.uk/lookalike.jpg"}],
        })

    matches = await make_search(handler).find(PNG, "image/png")
    assert [(m.domain, m.kind, m.title) for m in matches] == [
        ("reuters.com", "full", "Reuters story title"),
        ("factcheck.afp.com", "partial", "AFP fact check"),
        ("upload.wikimedia.org", "full", ""),
    ]


async def test_daily_limit_stops_calls_without_raising():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return vision_response({})

    search = make_search(handler, daily_limit=1)
    assert await search.find(PNG, "image/png") == []
    assert await search.find(PNG, "image/png") is None
    assert len(calls) == 1


async def test_http_error_raises_so_stage_marks_search_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"status": "PERMISSION_DENIED", "message": "Vision API not enabled"}})

    with pytest.raises(httpx.HTTPStatusError):
        await make_search(handler).find(PNG, "image/png")


async def test_per_image_error_in_body_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"responses": [{"error": {"message": "Bad image data"}}]})

    with pytest.raises(RuntimeError):
        await make_search(handler).find(PNG, "image/png")


async def test_unsupported_media_type_skips_without_calling_api():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call the API for SVG")

    assert await make_search(handler).find(b"<svg/>", "image/svg+xml") is None


def test_trusted_domain_matching_and_overrides():
    trusted = parse_trusted_domains("")
    assert is_trusted("commons.wikimedia.org", trusted)
    assert is_trusted("edition.cnn.com", trusted)
    assert not is_trusted("notcnn.com", trusted)
    assert not is_trusted("cnn.com.evil.example", trusted)
    assert parse_trusted_domains(" Example.org, news.test ") == ("example.org", "news.test")
