"""AI-image detector adapter (stage 5). Swap providers by implementing `Detector`."""
from __future__ import annotations

from typing import Protocol

import httpx

from ..models import DetectorSignal


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


class HttpDetector:
    """Generic HTTP detector. The request/response shape is a placeholder until the
    provider's docs are confirmed (open item in plan.md). Adjust `_parse` only."""

    name = "http-detector"

    def __init__(self, url: str, api_key: str | None, threshold: float, timeout: float = 8.0):
        self.url = url
        self.api_key = api_key
        self.threshold = threshold
        self.timeout = timeout

    async def score(self, image: bytes, media_type: str) -> DetectorSignal | None:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                self.url,
                headers=headers,
                files={"media": ("image", image, media_type)},
            )
            r.raise_for_status()
            return self._parse(r.json())

    def _parse(self, data: dict) -> DetectorSignal | None:
        # Placeholder: many providers return {"type": {"ai_generated": 0.97}} or {"score": 0.97}
        score = None
        if isinstance(data.get("score"), (int, float)):
            score = float(data["score"])
        elif isinstance(data.get("type"), dict):
            score = data["type"].get("ai_generated")
        if score is None:
            return None
        return DetectorSignal(provider=self.name, score=float(score), threshold=self.threshold)


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
