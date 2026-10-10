import io

import pytest
from PIL import Image

from factcheck.config import Settings
from factcheck.deps import Deps
from factcheck.llm.fake import FakeLLM
from factcheck.services.c2pa import StaticCredentialsReader
from factcheck.services.detector import StaticDetector
from factcheck.services.factcheck_api import StaticFactCheckClient
from factcheck.store.memory import InMemoryStore


def make_image(seed: int = 1, size=(64, 64), fmt="PNG", quality=95) -> bytes:
    """A deterministic photo-like image: smooth gradient plus a few shapes placed by seed."""
    from PIL import ImageDraw

    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(w):
        for y in range(h):
            px[x, y] = (int(255 * x / w), int(255 * y / h), (seed * 37) % 256)
    draw = ImageDraw.Draw(img)
    for i in range(3):
        cx = int(w * (((seed * 53 + i * 71) % 100) / 100))
        cy = int(h * (((seed * 29 + i * 43) % 100) / 100))
        r = w // 6 + i * (w // 20)
        colour = ((seed * 91 + i * 60) % 256, (seed * 17 + i * 120) % 256, (i * 80) % 256)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=quality)
    return buf.getvalue()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm_backend="fake", trace_dir=str(tmp_path / "traces"), stage_timeout=5,
        image_context_url=None,
        image_vision_enabled=False,
    )


@pytest.fixture
def deps(settings):
    return Deps(
        settings=settings,
        store=InMemoryStore(phash_max_distance=settings.phash_max_distance),
        llm=FakeLLM(),
        factcheck=StaticFactCheckClient(),
        detector=StaticDetector(score=None),
        credentials=StaticCredentialsReader(None),
    )
