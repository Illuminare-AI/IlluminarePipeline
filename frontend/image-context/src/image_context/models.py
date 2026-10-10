from typing import Any
from pydantic import BaseModel, Field, model_validator


class ImageSource(BaseModel):
    url: str | None = Field(default=None, max_length=4096)
    base64: str | None = Field(default=None, max_length=14_000_000)

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.url) == bool(self.base64):
            raise ValueError("Provide exactly one of url or base64")
        return self


class AnalysisRequest(BaseModel):
    images: list[ImageSource] = Field(min_length=1, max_length=4)
    context: dict[str, str] = Field(default_factory=dict)
    include_vision: bool = True

    @model_validator(mode="after")
    def bounded_context(self):
        if len(self.context) > 12 or sum(len(k) + len(v) for k, v in self.context.items()) > 30_000:
            raise ValueError("Context exceeds 30,000 characters or 12 fields")
        return self


class Observation(BaseModel):
    description: str
    scene: str
    objects: list[str]
    layout: list[str]
    additional_visible_text: list[str]
    claims_visible: list[str]
    uncertainties: list[str]


class ImageResult(BaseModel):
    source: str
    metadata: dict[str, Any]
    ocr: dict[str, Any]
    vision: dict[str, Any]
    warnings: list[str]


class AnalysisResult(BaseModel):
    schema_version: str = "1.0"
    context: dict[str, str]
    images: list[ImageResult]
    limitations: list[str] = [
        "OCR and model descriptions may be incorrect.",
        "Visible claims are extracted, not fact-checked.",
        "Image descriptions do not establish authenticity, identity, or provenance.",
    ]
