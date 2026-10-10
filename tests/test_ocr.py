import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from factcheck.api import create_app
from factcheck.models import Post
from factcheck.pipeline import check
from factcheck.services.ocr import read_image_text
from tests.conftest import make_image


async def test_adapter_sends_image_and_server_key_with_vision_disabled(settings, monkeypatch):
    image = make_image()
    settings.image_context_url = "http://ocr.local/"
    settings.image_context_api_key = "server-secret"
    real_client = httpx.AsyncClient

    def handler(request):
        assert str(request.url) == "http://ocr.local/analyze"
        assert request.headers["X-API-Key"] == "server-secret"
        body = json.loads(request.content)
        assert base64.b64decode(body["images"][0]["base64"]) == image
        assert body["include_vision"] is False
        assert body["context"]["body"] == "context"
        return httpx.Response(200, json={"images": [{"ocr": {"status": "ok", "text": "Visible text"}}]})

    monkeypatch.setattr("factcheck.services.ocr.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    assert await read_image_text(Post(image=image, caption="context"), settings) == "Visible text"


def test_automatic_ocr_reaches_api_claims(deps, monkeypatch):
    deps.settings.image_context_url = "http://ocr.local"

    async def ocr(post, settings):
        return "Egg prices rose 5% in March 2025."

    monkeypatch.setattr("factcheck.pipeline.read_image_text", ocr)
    client = TestClient(create_app(deps))
    response = client.post("/check", files={"image": ("post.png", make_image(), "image/png")})
    assert response.status_code == 200
    card = response.json()
    assert card["analysis_mode"] == "fake"
    assert card["stages"]["ocr"]["state"] == "ok"
    assert card["extraction"]["ocr_text"] == "Egg prices rose 5% in March 2025."
    assert len(card["claims"]) == 1


@pytest.mark.parametrize("failure", ["failed", "timeout"])
async def test_ocr_failure_preserves_caption_check(deps, monkeypatch, failure):
    deps.settings.image_context_url = "http://ocr.local"
    deps.settings.ocr_timeout = 0.01

    async def ocr(post, settings):
        if failure == "timeout":
            await asyncio.sleep(1)
        raise ValueError("OCR unavailable")

    monkeypatch.setattr("factcheck.pipeline.read_image_text", ocr)
    card = await check(Post(image=make_image(), caption="Egg prices rose 5%."), deps)
    assert card.stages["ocr"].state == failure
    assert len(card.claims) == 1
    assert card.origin.status != "unavailable"


async def test_manual_override_bypasses_ocr_and_invalidates_image_cache(deps, monkeypatch):
    deps.settings.image_context_url = "http://ocr.local"

    async def unexpected(*args):
        pytest.fail("Manual image text must override automatic OCR")

    monkeypatch.setattr("factcheck.pipeline.read_image_text", unexpected)
    image = make_image()
    first = await check(Post(image=image, ocr_text="Egg prices rose 5%."), deps)
    second = await check(Post(image=image, ocr_text="Egg prices fell 5%."), deps)
    assert not second.from_memory
    assert first.claims[0].claim != second.claims[0].claim
    assert second.stages["ocr"].detail == "text supplied"


async def test_replay_uses_original_input_after_automatic_ocr(deps, monkeypatch):
    deps.settings.image_context_url = "http://ocr.local"

    async def ocr(*args):
        return "Egg prices rose 5%."

    monkeypatch.setattr("factcheck.pipeline.read_image_text", ocr)
    post = Post(image=make_image())
    first = await check(post, deps)
    deps.settings.replay_mode = True
    replay = await check(post, deps)
    assert replay.check_id == first.check_id
    assert replay.analysis_mode == "replay"


def test_transcribed_text_only_is_valid_input(deps):
    client = TestClient(create_app(deps))
    response = client.post("/check", data={"ocr_text": "Egg prices rose 5%."})
    assert response.status_code == 200
    assert len(response.json()["claims"]) == 1
