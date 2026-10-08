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
