"""Stage 5: provenance and detector signals. Fixed rule order; never touches claim labels."""
from __future__ import annotations

import asyncio

from ..models import OriginResult
from ..services.c2pa import CredentialsReader
from ..services.detector import Detector
from ..services.fingerprint import sniff_media_type

NO_SIGNAL_NOTE = (
    "No provenance data or detector signal was found. This is not verification that the image "
    "is authentic; detectors miss many generated images, especially after platform recompression."
)


async def origin_signals(
    image: bytes | None, credentials: CredentialsReader, detector: Detector, threshold: float
) -> OriginResult:
    if not image:
        return OriginResult(status="unavailable", note="No image was provided.")
    media_type = sniff_media_type(image)

    async def safe(coro):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            return exc

    creds, signal = await asyncio.gather(
        safe(credentials.read(image, media_type)), safe(detector.score(image, media_type))
    )
    creds_err = isinstance(creds, Exception)
    det_err = isinstance(signal, Exception)
    creds = None if creds_err else creds
    signal = None if det_err else signal

    if creds is not None:
        gen = f" Generator: {creds.generator}." if creds.generator else ""
        return OriginResult(
            status="credentials_present",
            credentials=creds,
            detector=signal,
            note=f"Content Credentials are present (issuer: {creds.issuer or 'unknown'}).{gen} "
            "This reports what the credentials state; it is not a judgement of truth.",
        )
    if signal is not None and signal.score >= threshold:
        return OriginResult(
            status="possible_ai_signal",
            detector=signal,
            note=f"{signal.provider} scored this image {signal.score:.2f} (threshold "
            f"{signal.threshold:.2f}). Detectors are unreliable on recompressed images; treat as a "
            "signal, not a conclusion.",
        )
    if creds_err and det_err:
        return OriginResult(status="unavailable", note="Provenance and detector checks both failed.")
    note = NO_SIGNAL_NOTE
    if det_err or (signal is None and not det_err):
        note += " The detector was not available for this check."
    return OriginResult(status="no_signal_found", detector=signal, note=note)
