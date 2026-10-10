"""AI-image detector adapter (stage 5). Swap providers by implementing `Detector`.

The production adapter targets the Walter Writes AI image detector:
https://docs.walterwrites.ai/api-reference/image-detector
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx

from ..models import DetectorSignal

log = logging.getLogger(__name__)

WALTERWRITES_IMAGE_DETECTION_URL = "https://developer-portal.walterwrites.ai/api/image-detector/predict/"

# Walter Writes accepts JPEG, PNG, WebP, GIF, BMP and TIFF; anything else returns 400 invalid_payload.
WALTERWRITES_SUPPORTED_MEDIA_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff"}
)
WALTERWRITES_MAX_BYTES = 10 * 1024 * 1024

_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


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


class WalterWritesDetector:
    """Walter Writes AI image detection (POST /api/image-detector/predict/).

    Request: multipart/form-data with the image in `file`; `X-API-Key` header with the
    `image_detector` scope. Response: `prediction` ("real", "fake" or "inpainting"),
    `confidence`, and `probabilities` for the three classes summing to about 1.

    The signal we emit is the probability that AI was involved at all, i.e.
    `fake + inpainting` (equivalently `1 - real`), so that `score >= threshold` keeps its
    meaning in stage 5: "fake" is a fully generated image, "inpainting" is a real image with
    AI-edited regions. Both are AI signals for a fact-check card.

    Provider constraints worth knowing: files up to 10 MB, pricing by megapixel (6 credits
    minimum, 17 at 4K and above), and a per-plan rate limit of 5 requests/min on the trial
    plan (429 when exceeded). Failures raise, and stage 5 reports the detector as
    unavailable rather than guessing. Failed requests are refunded by the provider.
    """

    name = "walterwrites"

    def __init__(
        self,
        api_key: str,
        url: str = WALTERWRITES_IMAGE_DETECTION_URL,
        threshold: float = 0.9,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.url = url
        self.api_key = api_key
        self.threshold = threshold
        self.timeout = timeout
        self._transport = transport

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        if media_type not in WALTERWRITES_SUPPORTED_MEDIA_TYPES:
            log.info("walterwrites: skipping unsupported media type %s", media_type)
            return None
        if len(image) > WALTERWRITES_MAX_BYTES:
            log.info("walterwrites: skipping image of %d bytes (limit 10 MB)", len(image))
            return None
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        files = {"file": (f"image.{_EXTENSIONS[media_type]}", image, media_type)}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            r = await client.post(self.url, headers=headers, files=files)
            if r.status_code >= 400:
                detail = ""
                try:
                    err = r.json()
                    if isinstance(err, dict):
                        parts = [str(err[k]) for k in ("code", "error", "detail", "message") if err.get(k)]
                        detail = " " + ": ".join(parts) if parts else ""
                except ValueError:
                    pass
                log.warning("walterwrites: HTTP %s%s", r.status_code, detail)
                r.raise_for_status()
            return self._parse(r.json())

    def _parse(self, data: Any) -> DetectorSignal | None:
        if not isinstance(data, dict):
            return None
        probs = data.get("probabilities")
        probs = probs if isinstance(probs, dict) else {}
        verdict = data.get("prediction")
        verdict = verdict if isinstance(verdict, str) else None

        fake, inpainting, real = (_number(probs.get(k)) for k in ("fake", "inpainting", "real"))
        if fake is not None or inpainting is not None:
            score = (fake or 0.0) + (inpainting or 0.0)
        elif real is not None:
            score = 1.0 - real
        else:
            # No class breakdown: fall back to the verdict's own confidence.
            confidence = _number(data.get("confidence"))
            if verdict is None or confidence is None:
                return None
            score = 1.0 - confidence if verdict == "real" else confidence
        score = min(1.0, max(0.0, score))
        return DetectorSignal(provider=self.name, score=score, threshold=self.threshold, verdict=verdict)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


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
