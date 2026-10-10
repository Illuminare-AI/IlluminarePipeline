"""Reverse image search for stage 5: where else has this image been published?

The production adapter uses Google Cloud Vision web detection, which returns pages that embed
the same image or a cropped/resized copy of it. Only pages on an allowlist of reputable domains
(Wikimedia, wire services, established newsrooms, fact-checkers) are kept, so the card never
cites content farms or reposts.

Cost control: Vision web detection is free for the first 1,000 images a month and about
US$1.50 per 1,000 after that. A per-process daily cap (`REVERSE_IMAGE_DAILY_LIMIT`, default 30)
keeps the default well inside the free tier; once the cap is hit the search reports itself as
unavailable rather than spending. The counter is in memory and resets when the process restarts.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from ..models import ImageMatch

log = logging.getLogger(__name__)

GOOGLE_VISION_ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"

SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"})

# Subdomains match too (commons.wikimedia.org, factcheck.afp.com, edition.cnn.com).
DEFAULT_TRUSTED_DOMAINS: tuple[str, ...] = (
    # archives and institutions
    "wikimedia.org", "wikipedia.org", "europeana.eu", "loc.gov", "archives.gov", "nationalarchives.gov.uk",
    "nasa.gov", "esa.int", "noaa.gov", "usgs.gov",
    # wire services and photo agencies
    "reuters.com", "apnews.com", "afp.com", "gettyimages.com",
    # newsrooms
    "bbc.co.uk", "bbc.com", "theguardian.com", "nytimes.com", "washingtonpost.com", "wsj.com", "ft.com",
    "bloomberg.com", "economist.com", "npr.org", "pbs.org", "cnn.com", "nbcnews.com", "cbsnews.com",
    "abcnews.go.com", "aljazeera.com", "dw.com", "france24.com", "lemonde.fr", "spiegel.de", "euronews.com",
    "cbc.ca", "abc.net.au", "smh.com.au", "nhk.or.jp", "thehindu.com", "indianexpress.com", "time.com",
    # fact-checkers
    "snopes.com", "factcheck.org", "politifact.com", "fullfact.org",
)

MAX_MATCHES = 5


class ReverseImageSearch(Protocol):
    name: str

    async def find(self, image: bytes, media_type: str) -> list[ImageMatch] | None:
        """Matches on trusted domains; [] when none; None when the search could not run."""
        ...


class NullReverseImageSearch:
    """Not configured. Stage 5 says nothing about where the image has appeared."""

    name = "none"

    async def find(self, image: bytes, media_type: str) -> list[ImageMatch] | None:
        return None


def domain_of(url: str) -> str:
    host = urlsplit(url.strip()).hostname or ""
    return re.sub(r"^www\.", "", host.lower())


def is_trusted(host: str, trusted: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in trusted)


def parse_trusted_domains(value: str | None) -> tuple[str, ...]:
    items = tuple(d.strip().lower() for d in (value or "").split(",") if d.strip())
    return items or DEFAULT_TRUSTED_DOMAINS


class GoogleVisionReverseImageSearch:
    """Google Cloud Vision `images:annotate` with the WEB_DETECTION feature.

    Request: JSON with the base64 image in `requests[0].image.content`; the API key goes in the
    `x-goog-api-key` header (any Google API key with the Vision API enabled on its project).
    Response: `webDetection.pagesWithMatchingImages` (pages, with `fullMatchingImages` or
    `partialMatchingImages` per page) plus top-level `fullMatchingImages` and
    `partialMatchingImages` (image file URLs). Visually similar images are ignored: they are
    lookalikes, not copies.
    """

    name = "google-vision"

    def __init__(
        self,
        api_key: str,
        url: str = GOOGLE_VISION_ANNOTATE_URL,
        trusted_domains: tuple[str, ...] = DEFAULT_TRUSTED_DOMAINS,
        daily_limit: int = 30,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.url = url
        self.trusted = trusted_domains
        self.daily_limit = daily_limit
        self.timeout = timeout
        self._transport = transport
        self._day: str = ""
        self._used = 0

    def _budget_ok(self) -> bool:
        today = datetime.now(UTC).date().isoformat()
        if today != self._day:
            self._day, self._used = today, 0
        if self._used >= self.daily_limit:
            return False
        self._used += 1
        return True

    async def find(self, image: bytes, media_type: str) -> list[ImageMatch] | None:
        if media_type not in SUPPORTED_MEDIA_TYPES:
            log.info("reverse image: skipping unsupported media type %s", media_type)
            return None
        if not self._budget_ok():
            log.info("reverse image: daily limit of %d reached; skipping", self.daily_limit)
            return None
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": 20}],
                }
            ]
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            r = await client.post(self.url, headers=headers, json=body)
            if r.status_code >= 400:
                detail = ""
                try:
                    err = r.json().get("error", {})
                    detail = f" {err.get('status', '')}: {err.get('message', '')}".rstrip(": ")
                except (ValueError, AttributeError):
                    pass
                log.warning("reverse image: HTTP %s%s", r.status_code, detail)
                r.raise_for_status()
            return self._parse(r.json())

    def _parse(self, data: Any) -> list[ImageMatch]:
        try:
            response = data["responses"][0]
        except (KeyError, IndexError, TypeError):
            return []
        if "error" in response:
            raise RuntimeError(f"vision error: {response['error'].get('message', 'unknown')}")
        web = response.get("webDetection") or {}
        found: dict[str, ImageMatch] = {}

        def add(url: str | None, title: str, kind: str) -> None:
            if not url:
                return
            host = domain_of(url)
            key = re.sub(r"[#?].*$", "", url.strip().lower().rstrip("/"))
            if not is_trusted(host, self.trusted) or key in found:
                return
            found[key] = ImageMatch(url=url.strip(), domain=host, title=_clean_title(title), kind=kind)  # type: ignore[arg-type]

        for page in web.get("pagesWithMatchingImages") or []:
            kind = "full" if page.get("fullMatchingImages") else "partial" if page.get("partialMatchingImages") else "page"
            add(page.get("url"), page.get("pageTitle") or "", kind)
        for item in web.get("fullMatchingImages") or []:
            add(item.get("url"), "", "full")
        for item in web.get("partialMatchingImages") or []:
            add(item.get("url"), "", "partial")
        return list(found.values())[:MAX_MATCHES]


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()


class StaticReverseImageSearch:
    """Test double: fixed matches, None for 'not available', or an exception to raise."""

    name = "static-reverse-image"

    def __init__(self, matches: list[ImageMatch] | None, error: Exception | None = None) -> None:
        self._matches = matches
        self._error = error

    async def find(self, image: bytes, media_type: str) -> list[ImageMatch] | None:
        if self._error:
            raise self._error
        return self._matches
