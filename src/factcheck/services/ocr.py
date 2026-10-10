"""Server-side adapter to the companion image-context service (OCR only)."""
import base64

import httpx

from ..config import Settings
from ..models import Post


async def read_image_text(post: Post, settings: Settings) -> str:
    headers = {}
    if settings.image_context_api_key:
        headers["X-API-Key"] = settings.image_context_api_key
    async with httpx.AsyncClient(timeout=settings.ocr_timeout) as client:
        response = await client.post(
            f"{settings.image_context_url.rstrip('/')}/analyze",
            headers=headers,
            json={
                "images": [{"base64": base64.b64encode(post.image).decode()}],
                "context": {"body": post.caption or ""},
                "include_vision": False,
            },
        )
        response.raise_for_status()
        ocr = response.json()["images"][0]["ocr"]
        if ocr.get("status") != "ok" or not isinstance(ocr.get("text"), str):
            raise ValueError("Image text extraction is unavailable")
        return ocr["text"]
