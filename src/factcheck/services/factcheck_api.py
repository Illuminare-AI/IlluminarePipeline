"""Google Fact Check Tools `claims:search` adapter (stage 3)."""
from __future__ import annotations

import re
from typing import Protocol

import httpx
from pydantic import BaseModel

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is", "are", "was",
    "were", "that", "this", "with", "by", "from", "as", "it", "its", "has", "have", "had",
}


class ClaimReview(BaseModel):
    claim_text: str = ""
    claimant: str = ""
    publisher: str = ""
    url: str = ""
    title: str = ""
    rating: str = ""
    review_date: str = ""


class FactCheckClient(Protocol):
    async def search(self, query: str) -> list[ClaimReview]: ...


def keyword_query(claim: str, max_words: int = 8) -> str:
    """Shortened keyword version of a claim for a second, looser search."""
    words = [w for w in re.findall(r"[A-Za-z0-9%$.]+", claim) if w.lower() not in _STOPWORDS]
    return " ".join(words[:max_words])


class GoogleFactCheckClient:
    def __init__(self, api_key: str, url: str, timeout: float = 8.0) -> None:
        self.api_key = api_key
        self.url = url
        self.timeout = timeout

    async def search(self, query: str) -> list[ClaimReview]:
        params = {"query": query, "key": self.api_key, "languageCode": "en", "pageSize": 10}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(self.url, params=params)
            r.raise_for_status()
            data = r.json()
        reviews: list[ClaimReview] = []
        for claim in data.get("claims", []):
            for rev in claim.get("claimReview", []):
                reviews.append(
                    ClaimReview(
                        claim_text=claim.get("text", ""),
                        claimant=claim.get("claimant", ""),
                        publisher=(rev.get("publisher") or {}).get("name", ""),
                        url=rev.get("url", ""),
                        title=rev.get("title", ""),
                        rating=rev.get("textualRating", ""),
                        review_date=rev.get("reviewDate", ""),
                    )
                )
        return reviews


class NullFactCheckClient:
    """Used when no API key is configured; stage 3 is marked skipped."""

    async def search(self, query: str) -> list[ClaimReview]:
        return []


class StaticFactCheckClient:
    """Test double: returns canned reviews for queries containing a keyword."""

    def __init__(self, canned: dict[str, list[ClaimReview]] | None = None) -> None:
        self.canned = canned or {}
        self.queries: list[str] = []

    async def search(self, query: str) -> list[ClaimReview]:
        self.queries.append(query)
        for key, reviews in self.canned.items():
            if key.lower() in query.lower():
                return reviews
        return []


class FactCheckUnavailable(Exception):
    pass


