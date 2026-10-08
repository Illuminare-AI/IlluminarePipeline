"""Content Credentials (C2PA) reader (stage 5). Optional dependency: c2pa-python."""
from __future__ import annotations

import json
import tempfile
from typing import Protocol

from ..models import Credentials


class CredentialsReader(Protocol):
    async def read(self, image: bytes, media_type: str) -> Credentials | None: ...


class NullCredentialsReader:
    async def read(self, image: bytes, media_type: str) -> Credentials | None:
        return None


class C2paReader:
    """Reads a manifest with c2pa-python. Returns None when there is no manifest.

    The c2pa-python API has changed across versions; this wraps the file-path reader, which
    has been the most stable entry point. Verify against the installed version.
    """

    async def read(self, image: bytes, media_type: str) -> Credentials | None:
        try:
            import c2pa  # type: ignore
        except ImportError:
            return None
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
            media_type, ".bin"
        )
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(image)
            tmp.flush()
            try:
                reader = c2pa.Reader(tmp.name)
                manifest = json.loads(reader.json())
            except Exception:
                return None
        active = manifest.get("active_manifest")
        m = (manifest.get("manifests") or {}).get(active, {})
        if not m:
            return None
        generator = m.get("claim_generator") or m.get("claim_generator_info", [{}])[0].get("name")
        actions: list[str] = []
        for a in m.get("assertions", []):
            if a.get("label", "").startswith("c2pa.actions"):
                for act in (a.get("data") or {}).get("actions", []):
                    if act.get("action"):
                        actions.append(act["action"])
        issuer = ((m.get("signature_info") or {}).get("issuer")) or ""
        return Credentials(issuer=issuer, generator=generator, actions=actions, raw=m)


class StaticCredentialsReader:
    def __init__(self, creds: Credentials | None) -> None:
        self._creds = creds

    async def read(self, image: bytes, media_type: str) -> Credentials | None:
        return self._creds
