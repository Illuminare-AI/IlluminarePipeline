import base64

from fastapi.testclient import TestClient

from factcheck.api import create_app
from tests.conftest import make_image


def test_multipart_and_json(deps):
    client = TestClient(create_app(deps))
    r = client.post("/check", files={"image": ("a.png", make_image(2), "image/png")}, data={"caption": "hi"})
    assert r.status_code == 200
    card = r.json()
    assert "origin" in card and "stages" in card
    r2 = client.post("/check", json={"image_base64": base64.b64encode(make_image(2)).decode(), "caption": "hi"})
    assert r2.status_code == 200
    assert r2.json()["from_memory"] is True
    assert client.get(f"/checks/{card['check_id']}/trace").status_code == 200
    assert client.post("/check", json={}).status_code == 400


def test_ocr_text_accepted_on_both_content_types(deps):
    client = TestClient(create_app(deps))
    ocr = "Share before it's deleted! Egg prices rose 5% in March 2025."
    r = client.post(
        "/check",
        files={"image": ("a.png", make_image(3), "image/png")},
        data={"caption": "look", "ocr_text": ocr},
    )
    assert r.status_code == 200
    assert r.json()["extraction"]["ocr_text"] == ocr
    r2 = client.post(
        "/check",
        json={"image_base64": base64.b64encode(make_image(3)).decode(), "caption": "look", "ocr_text": ocr},
    )
    assert r2.status_code == 200
    assert r2.json()["extraction"]["ocr_text"] == ocr


def test_describe_image_false_skips_the_description(deps):
    """A client that already has the post text can ask for OCR and the detector without the vision model."""
    deps.settings.image_vision_enabled = True
    client = TestClient(create_app(deps))
    r = client.post(
        "/check",
        files={"image": ("a.png", make_image(2), "image/png")},
        data={"caption": "hi", "describe_image": "false"},
    )
    assert r.status_code == 200
    assert r.json()["stages"]["vision"] == {"state": "skipped", "ms": 0, "detail": "description not requested"}
    r2 = client.post("/check", json={"caption": "hi", "image_base64": base64.b64encode(make_image(2)).decode(), "describe_image": False})
    assert r2.json()["stages"]["vision"]["detail"] == "description not requested"
