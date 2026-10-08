"""Stage 0 helpers: perceptual hash and image media type sniffing. No LLM."""
from __future__ import annotations

import io


def sniff_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def phash(data: bytes) -> str:
    """64-bit perceptual hash as a 16-char hex string. Raises on undecodable images."""
    import imagehash
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    return str(imagehash.phash(img))


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")
