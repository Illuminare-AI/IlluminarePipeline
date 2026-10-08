"""AI-image detector adapter (stage 5). Swap providers by implementing `Detector`.

The production adapter targets Winston AI's image detection endpoint:
https://docs.gowinston.ai/api-reference/v2/image-detection/post
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Protocol

import httpx

from ..models import DetectorSignal

log = logging.getLogger(__name__)

WINSTON_IMAGE_DETECTION_URL = "https://api.gowinston.ai/v2/image-detection"

# Winston accepts JPG, JPEG, PNG and WEBP only; anything else is rejected with 415.
WINSTON_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class Detector(Protocol):
    name: str

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        """Return a signal, or None when the detector could not run."""
        ...


class NullDetector:
    """No detector configured. Stage 5 reports 'unavailable' for the detector half."""

    name = "none"

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        return None


class WinstonDetector:
    """Winston AI image detection (POST /v2/image-detection).

    Request: JSON with a base64 data URL in `image` (or a public `url`), optional `version`.
    Response: `ai_probability` and `human_probability` in [0, 1], and `score` as a 0-100
    *human* probability. The signal we emit is the AI probability so that
    `score >= threshold` keeps its meaning in stage 5.

    Provider constraints worth knowing: images must be at least 256x256, roughly 4 MB or
    less, and each call costs 300 credits. Failures raise, and stage 5 reports the detector
    as unavailable rather than guessing.
    """

    name = "winston-ai"

    def __init__(
        self,
        api_key: str,
        url: str = WINSTON_IMAGE_DETECTION_URL,
        threshold: float = 0.9,
        version: str | None = None,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url
        self.api_key = api_key
        self.threshold = threshold
        self.version = version
        self.timeout = timeout
        self._transport = transport

    def _body(self, image: bytes, media_type: str) -> dict[str, Any]:
        data_url = f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"
        body: dict[str, Any] = {"image": data_url}
        if self.version:
            body["version"] = self.version
        return body

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        if media_type not in WINSTON_SUPPORTED_MEDIA_TYPES:
            log.info("winston: skipping unsupported media type %s", media_type)
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            r = await client.post(self.url, headers=headers, json=self._body(image, media_type))
            if r.status_code >= 400:
                detail = ""
                try:
                    err = r.json()
                    detail = f" {err.get('error', '')}: {err.get('description', '')}".rstrip(": ")
                except ValueError:
                    pass
                log.warning("winston: HTTP %s%s", r.status_code, detail)
                r.raise_for_status()
            return self._parse(r.json())

    def _parse(self, data: dict[str, Any]) -> DetectorSignal | None:
        ai = data.get("ai_probability")
        if isinstance(ai, (int, float)) and not isinstance(ai, bool):
            score = float(ai)
        else:
            # Fall back to `score`, which Winston defines as human probability on 0-100.
            human = data.get("score")
            if not isinstance(human, (int, float)) or isinstance(human, bool):
                return None
            score = 1.0 - float(human) / 100.0
        score = min(1.0, max(0.0, score))
        return DetectorSignal(provider=self.name, score=score, threshold=self.threshold)


class StaticDetector:
    """Test double with a fixed score."""

    name = "static-detector"

    def __init__(self, score: float | None, threshold: float = 0.9) -> None:
        self._score = score
        self.threshold = threshold

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        if self._score is None:
            return None
        return DetectorSignal(provider=self.name, score=self._score, threshold=self.threshold)
