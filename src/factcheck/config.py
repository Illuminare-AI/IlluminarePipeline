"""Settings loaded from environment variables or a .env file."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_backend: Literal["anthropic", "fake"] = "fake"
    llm_model: str = "claude-opus-5"
    llm_fast_model: str = "claude-haiku-4-5"  # report structuring and self-check
    anthropic_api_key: str | None = None

    factcheck_api_key: str | None = None
    factcheck_url: str = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    # Walter Writes AI image detection. The detector is enabled when the API key is set.
    detector_api_key: str | None = None
    detector_url: str = "https://developer-portal.walterwrites.ai/api/image-detector/predict/"
    detector_threshold: float = 0.9  # on P(fake) + P(inpainting) in [0, 1]

    # Reverse image search (Google Cloud Vision web detection). Enabled when the API key is set.
    # Any Google API key whose project has the Vision API enabled works.
    reverse_image_api_key: str | None = None
    reverse_image_url: str = "https://vision.googleapis.com/v1/images:annotate"
    reverse_image_daily_limit: int = 30  # per process; about 900/month stays inside the free tier
    reverse_image_trusted_domains: str = ""  # comma-separated; empty uses the built-in list

    phash_max_distance: int = 10

    stage_timeout: float = 30.0
    web_stage_timeout: float = 180.0

    trace_dir: str = "traces"
    replay_mode: bool = False
    postgres_url: str | None = None
    image_context_url: str | None = None
    image_context_api_key: str | None = None
    ocr_timeout: float = 25.0
    image_vision_enabled: bool = True
    image_context_timeout: float = 600.0


def load_settings() -> Settings:
    return Settings()
