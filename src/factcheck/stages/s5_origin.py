"""Stage 5: provenance and detector signals. Fixed rule order; never touches claim labels.

Three independent lookups run together: Content Credentials (C2PA), an AI-image detector, and a
reverse image search limited to reputable publishers. Rule order: credentials, then a detector
score over the threshold, then reputable matches, then "no signal". A reputable match says where
the image has been published; it does not say the post uses it honestly, and it does not rule out
a generated image that newsrooms are reporting on.
"""
from __future__ import annotations

import asyncio

from ..models import ImageMatch, OriginResult
from ..services.c2pa import CredentialsReader
from ..services.detector import Detector
from ..services.fingerprint import sniff_media_type
from ..services.reverse_image import ReverseImageSearch

NO_SIGNAL_NOTE = (
    "No provenance data or detector signal was found. This is not verification that the image "
    "is authentic; detectors miss many generated images, especially after platform recompression."
)


def _matches_sentence(matches: list[ImageMatch]) -> str:
    domains: list[str] = []
    for m in matches:
        if m.domain not in domains:
            domains.append(m.domain)
    shown = ", ".join(domains[:3]) + (f" and {len(domains) - 3} more" if len(domains) > 3 else "")
    partial = all(m.kind == "partial" for m in matches)
    what = "Part of this image" if partial else "This image"
    return f"{what} also appears on {len(domains)} reputable site{'s' if len(domains) != 1 else ''}: {shown}."


async def origin_signals(
    image: bytes | None,
    credentials: CredentialsReader,
    detector: Detector,
    threshold: float,
    reverse_image: ReverseImageSearch | None = None,
) -> OriginResult:
    if not image:
        return OriginResult(status="unavailable", note="No image was provided.")
    media_type = sniff_media_type(image)

    async def safe(coro):
        try:
            return await coro
        except Exception as exc:  # noqa: BLE001
            return exc

    async def none():
        return None

    creds, signal, found = await asyncio.gather(
        safe(credentials.read(image, media_type)),
        safe(detector.score(image, media_type)),
        safe(reverse_image.find(image, media_type)) if reverse_image else none(),
    )
    creds_err = isinstance(creds, Exception)
    det_err = isinstance(signal, Exception)
    search_err = isinstance(found, Exception)
    creds = None if creds_err else creds
    signal = None if det_err else signal
    matches: list[ImageMatch] = [] if search_err or found is None else list(found)
    match_note = f" {_matches_sentence(matches)}" if matches else ""
    search_note = " The reverse image search was not available for this check." if search_err else ""

    if creds is not None:
        gen = f" Generator: {creds.generator}." if creds.generator else ""
        return OriginResult(
            status="credentials_present",
            credentials=creds,
            detector=signal,
            matches=matches,
            note=f"Content Credentials are present (issuer: {creds.issuer or 'unknown'}).{gen} "
            "This reports what the credentials state; it is not a judgement of truth." + match_note,
        )
    if signal is not None and signal.score >= threshold:
        caveat = (
            " A match on a reputable site does not rule out a generated image; the site may be reporting on it."
            if matches
            else ""
        )
        return OriginResult(
            status="possible_ai_signal",
            detector=signal,
            matches=matches,
            note=f"{signal.provider} scored this image {signal.score:.2f} (threshold "
            f"{signal.threshold:.2f}). Detectors are unreliable on recompressed images; treat as a "
            "signal, not a conclusion." + match_note + caveat,
        )
    if matches:
        return OriginResult(
            status="matched_reputable_source",
            detector=signal,
            matches=matches,
            note=_matches_sentence(matches)
            + " That shows where the image has been published, not that this post uses it in its "
            "original context; compare the date, place and caption with the matched page.",
        )
    if creds_err and det_err:
        return OriginResult(status="unavailable", note="Provenance and detector checks both failed." + search_note)
    note = NO_SIGNAL_NOTE
    if det_err or (signal is None and not det_err):
        note += " The detector was not available for this check."
    return OriginResult(status="no_signal_found", detector=signal, note=note + search_note)
