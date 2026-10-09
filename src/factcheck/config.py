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

    # Winston AI image detection. The detector is enabled when the API key is set.
    detector_api_key: str | None = None
    detector_url: str = "https://api.gowinston.ai/v2/image-detection"
    detector_version: str | None = None  # Winston model version (e.g. "5"); None = API default
    detector_threshold: float = 0.9  # on ai_probability in [0, 1]

    phash_max_distance: int = 10

    stage_timeout: float = 10.0
    web_stage_timeout: float = 90.0

    trace_dir: str = "traces"
    replay_mode: bool = False
    postgres_url: str | None = None


def load_settings() -> Settings:
    return Settings()
