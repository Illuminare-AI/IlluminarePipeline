import base64
import json

import httpx
from fastapi.testclient import TestClient

from factcheck.api import create_app
from factcheck.models import LocalImageContext, Post
from factcheck.pipeline import check
from factcheck.services.ocr import read_image_context
from tests.conftest import make_image


def context(ocr_status="ok", vision_status="ok"):
    return LocalImageContext(
        ocr_status=ocr_status, ocr_text="Egg prices rose 5%.",
        vision_status=vision_status, model="local-test-model",
        observations={"description": "A red square on a white background.",
                      "objects": ["red square"], "additional_visible_text": ["Egg prices rose 5%."]}
        if vision_status == "ok" else None,
    )


async def test_vision_adapter_sends_uploaded_bytes_and_manual_text(settings, monkeypatch):
    settings.image_context_url = "http://images.local/"
    image = make_image()
    real_client = httpx.AsyncClient

    def handler(request):
        payload = json.loads(request.content)
        assert payload["include_vision"] is True
        assert base64.b64decode(payload["images"][0]["base64"]) == image
        assert payload["context"]["supplied_image_text"] == "manual override"
        return httpx.Response(200, json={"images": [{
            "ocr": {"status": "unavailable", "text": ""},
            "vision": {"status": "ok", "model": "local-test-model",
                       "observations": {"description": "A red square."}},
        }]})

    monkeypatch.setattr("factcheck.services.ocr.httpx.AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = await read_image_context(Post(image=image, ocr_text="manual override"), settings)
    assert result.observations.description == "A red square."
    assert result.ocr_status == "unavailable"


def test_uploaded_image_description_is_returned_even_with_manual_ocr(deps, monkeypatch):
    deps.settings.image_context_url = "http://images.local"
    deps.settings.image_vision_enabled = True
    seen = []

    async def analyze(post, settings):
        seen.append(post.image)
        return context()

    monkeypatch.setattr("factcheck.pipeline.read_image_context", analyze)
    image = make_image()
    response = TestClient(create_app(deps)).post(
        "/check", files={"image": ("upload.png", image, "image/png")},
        data={"ocr_text": "Egg prices fell 5%."},
    )
    assert response.status_code == 200
    card = response.json()
    assert seen == [image]
    assert card["image_context"]["observations"]["description"] == "A red square on a white background."
    assert card["extraction"]["image_description"] == card["image_context"]["observations"]["description"]
    assert card["extraction"]["ocr_text"] == "Egg prices fell 5%."
    assert card["stages"]["vision"]["state"] == "ok"


async def test_vision_failure_keeps_ocr_claims(deps, monkeypatch):
    deps.settings.image_context_url = "http://images.local"
    deps.settings.image_vision_enabled = True

    async def analyze(*args):
        return context(vision_status="unavailable")

    monkeypatch.setattr("factcheck.pipeline.read_image_context", analyze)
    card = await check(Post(image=make_image()), deps)
    assert card.stages["vision"].state == "failed"
    assert card.stages["ocr"].state == "ok"
    assert card.claims[0].claim == "Egg prices rose 5%."


async def test_ocr_failure_keeps_real_description_and_visible_text(deps, monkeypatch):
    deps.settings.image_context_url = "http://images.local"
    deps.settings.image_vision_enabled = True

    async def analyze(*args):
        return context(ocr_status="unavailable")

    monkeypatch.setattr("factcheck.pipeline.read_image_context", analyze)
    card = await check(Post(image=make_image()), deps)
    assert card.stages["ocr"].state == "failed"
    assert card.stages["vision"].state == "ok"
    assert card.image_context.observations.description
    assert card.claims[0].claim == "Egg prices rose 5%."


async def test_image_cache_retains_current_description_not_old_output(deps, monkeypatch):
    deps.settings.image_context_url = "http://images.local"
    deps.settings.image_vision_enabled = True
    count = 0

    async def analyze(*args):
        nonlocal count
        count += 1
        result = context()
        result.observations.description = f"Observation {count}"
        return result

    monkeypatch.setattr("factcheck.pipeline.read_image_context", analyze)
    post = Post(image=make_image())
    await check(post, deps)
    card = await check(post, deps)
    assert card.from_memory
    assert card.image_context.observations.description == "Observation 2"
    assert card.extraction.image_description == "Observation 2"
