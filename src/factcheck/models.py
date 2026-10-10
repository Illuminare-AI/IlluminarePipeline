"""Shared data contracts. These are the interfaces agreed with the input page and the store.

Changing a field here changes the API response shape, so coordinate with the frontend owner.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

# ---------- Input ----------


class Post(BaseModel):
    image: bytes | None = None
    caption: str | None = None
    ocr_text: str | None = None
    """Text in the image, transcribed by the frontend. The pipeline does not run OCR itself."""
    source_url: str | None = None

    def text(self) -> str:
        return self.caption or ""


# ---------- Labels and enums ----------

ClaimLabel = Literal["supported", "refuted", "missing_context", "not_enough_evidence"]
OriginStatus = Literal["credentials_present", "possible_ai_signal", "no_signal_found", "unavailable"]
TacticName = Literal["urgency", "authority", "fear", "promised_reward"]
EvidenceOrigin = Literal["memory", "fact_check_api", "web", "none"]
StageState = Literal["ok", "skipped", "failed", "timeout"]

# ---------- Stage outputs ----------


class Tactic(BaseModel):
    tactic: TacticName
    phrase: str = Field(description="Exact phrase from the caption or OCR text that triggered the tag")


class ExtractionOutput(BaseModel):
    """What the LLM returns in stage 1. OCR is supplied by the frontend, so it is not asked for."""

    image_description: str = ""
    claims: list[str] = Field(default_factory=list, max_length=3)
    persuasion: list[Tactic] = Field(default_factory=list)


class Extraction(ExtractionOutput):
    """Stage 1 result as stored on the card: the LLM output plus the frontend's OCR text."""

    ocr_text: str = ""


class Source(BaseModel):
    url: str
    title: str = ""
    publisher: str = ""
    quote: str = Field(default="", description="One quoted passage from the source")
    rating: str | None = Field(default=None, description="Publisher's own rating text, if a fact-check")


class ClaimResult(BaseModel):
    claim: str
    label: ClaimLabel
    explanation: str = ""
    sources: list[Source] = Field(default_factory=list)
    disputed_spans: list[str] = Field(default_factory=list)
    evidence_origin: EvidenceOrigin = "none"


class Credentials(BaseModel):
    issuer: str = ""
    generator: str | None = None
    actions: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class DetectorSignal(BaseModel):
    provider: str
    score: float
    threshold: float
    verdict: str | None = None  # provider label, e.g. "real", "fake", "inpainting"


class OriginResult(BaseModel):
    status: OriginStatus = "unavailable"
    credentials: Credentials | None = None
    detector: DetectorSignal | None = None
    note: str = Field(
        default="",
        description="Plain-language caveat. 'No signal found' is never 'verified authentic'.",
    )


class StageStatus(BaseModel):
    state: StageState
    ms: int = 0
    detail: str | None = None


class ImageObservation(BaseModel):
    description: str
    scene: str = ""
    objects: list[str] = Field(default_factory=list)
    layout: list[str] = Field(default_factory=list)
    additional_visible_text: list[str] = Field(default_factory=list)
    claims_visible: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class LocalImageContext(BaseModel):
    ocr_status: Literal["ok", "unavailable"]
    ocr_text: str = ""
    vision_status: Literal["ok", "unavailable", "disabled"]
    model: str | None = None
    observations: ImageObservation | None = None


# ---------- Card ----------


class Card(BaseModel):
    check_id: str
    analysis_mode: Literal["live", "fake", "replay", "unknown"] = "unknown"
    claims: list[ClaimResult] = Field(default_factory=list)
    origin: OriginResult = Field(default_factory=OriginResult)
    persuasion: list[Tactic] = Field(default_factory=list)
    from_memory: bool = False
    stages: dict[str, StageStatus] = Field(default_factory=dict)
    extraction: Extraction | None = None
    image_context: LocalImageContext | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def nothing_checkable(self) -> bool:
        return not self.claims


# ---------- Store contract ----------


class StoredCheck(BaseModel):
    check_id: str
    caption: str | None
    claims: list[str]
    phash: str | None
    card: Card


class Store(Protocol):
    async def find_media(self, phash: str) -> list[StoredCheck]: ...

    async def find_claims(self, text: str, k: int = 5) -> list[StoredCheck]: ...

    async def save(self, post: Post, card: Card, phash: str | None) -> None: ...


# ---------- LLM structured outputs (internal) ----------


class SameClaimVerdict(BaseModel):
    same: bool
    reason: str = ""


class FactCheckDecision(BaseModel):
    matches: bool
    review_index: int | None = None
    label: ClaimLabel | None = None
    reason: str = ""


class WebEvidence(BaseModel):
    label: ClaimLabel
    explanation: str = Field(description="At most three sentences")
    sources: list[Source] = Field(default_factory=list)
    disputed_spans: list[str] = Field(default_factory=list)


class SupportCheck(BaseModel):
    supported: list[bool] = Field(description="One entry per explanation sentence, in order")


class ClaimRevision(BaseModel):
    """One change proposed by the cross-claim review (stage 7). Omitted fields keep their value."""

    claim_index: int = Field(description="Index of the claim in the list you were given")
    label: ClaimLabel | None = Field(default=None, description="New label, or null to keep it")
    explanation: str | None = Field(
        default=None, description="Rewritten explanation of at most three sentences, or null to keep it"
    )
    borrow_sources: list[str] = Field(
        default_factory=list,
        description="URLs of sources attached to OTHER claims in the list that this claim should also cite",
    )
    reason: str = Field(default="", description="One sentence on why the change is needed")


class ReconcileOutput(BaseModel):
    revisions: list[ClaimRevision] = Field(default_factory=list)
