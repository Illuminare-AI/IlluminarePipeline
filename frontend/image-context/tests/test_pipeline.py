import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from image_context import pipeline
from image_context.api import app
from image_context.models import AnalysisRequest


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (100, 50), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_invalid_image_is_rejected():
    with pytest.raises(ValueError, match="Invalid"):
        pipeline.decode_image(b"not an image")


@pytest.mark.parametrize("url", ["http://i.redd.it/a.png", "https://localhost/a.png", "https://i.redd.it.evil.test/a.png", "https://user@i.redd.it/a.png", "https://i.redd.it:8000/a.png"])
def test_untrusted_urls_rejected_without_network(url):
    with pytest.raises(ValueError, match="allowed media host"):
        pipeline.download_image(url)


def test_ocr_passes_preserve_confidence_and_coordinates(monkeypatch):
    monkeypatch.setattr(pipeline.pytesseract, "image_to_data", lambda *a, **k: {
        "text": ["Hello", "world", ""], "conf": [90, 80, -1],
        "block_num": [1, 1, 1], "par_num": [1, 1, 1], "line_num": [1, 1, 1],
        "left": [10, 30, 0], "top": [4, 4, 0], "width": [20, 25, 0], "height": [10, 10, 0],
    })
    result = pipeline.extract_ocr(Image.new("RGB", (100, 50)))
    assert result["text"] == "Hello world"
    assert len(result["passes"]) == 2
    assert result["passes"][0]["words"][0]["confidence"] == 0.9
    assert result["passes"][1]["words"][0]["box"] == [5, 2, 10, 5]


def test_ollama_request_and_structured_response(monkeypatch):
    observation = {"description": "A white rectangle.", "scene": "blank", "objects": [], "layout": [], "additional_visible_text": [], "claims_visible": [], "uncertainties": []}
    def post(url, **kwargs):
        payload = kwargs["json"]
        assert url.endswith("/api/chat")
        assert payload["stream"] is False
        assert payload["format"]["type"] == "object"
        assert base64.b64decode(payload["messages"][1]["images"][0]).startswith(b"\x89PNG")
        assert "untrusted" in payload["messages"][0]["content"]
        return httpx.Response(200, json={"message": {"content": json.dumps(observation)}}, request=httpx.Request("POST", url))
    monkeypatch.setattr(pipeline.httpx, "post", post)
    result = pipeline.describe_image(Image.new("RGB", (100, 50)), "", {"title": "demo"})
    assert result["observations"] == observation


def test_partial_failure_preserves_metadata(monkeypatch):
    def unavailable(*args):
        raise pipeline.pytesseract.TesseractNotFoundError()
    monkeypatch.setattr(pipeline, "extract_ocr", unavailable)
    result = pipeline.analyze_image(image_bytes(), "fixture", {}, include_vision=False)
    assert result.metadata["width"] == 100
    assert result.ocr["status"] == "unavailable"
    assert result.vision["status"] == "disabled"
    assert result.warnings


def test_api_auth_validation_and_success(monkeypatch):
    monkeypatch.setenv("CONTEXT_API_KEY", "test-key")
    monkeypatch.setattr(pipeline, "extract_ocr", lambda image: {"status": "ok", "text": "fixture", "passes": []})
    client = TestClient(app)
    assert client.post("/analyze", json={}).status_code == 401
    headers = {"X-API-Key": "test-key"}
    assert client.post("/analyze", headers=headers, json={"images": []}).status_code == 422
    result = client.post("/analyze", headers=headers, json={"images": [{"base64": base64.b64encode(image_bytes()).decode()}], "context": {"title": "demo"}, "include_vision": False})
    assert result.status_code == 200
    assert result.json()["images"][0]["ocr"]["text"] == "fixture"
    assert result.json()["context"]["title"] == "demo"


def test_one_source_and_context_bounds():
    with pytest.raises(ValueError):
        AnalysisRequest(images=[{"url": "https://i.redd.it/a", "base64": "abc"}])
    with pytest.raises(ValueError):
        AnalysisRequest(images=[{"base64": "abc"}], context={"body": "x" * 30001})
