"""Settings loaded from environment variables or a .env file."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_backend: Literal["anthropic", "fake"] = "fake"
    llm_model: str = "claude-opus-5"
    anthropic_api_key: str | None = None

    factcheck_api_key: str | None = None
    factcheck_url: str = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    detector_url: str | None = None
    detector_api_key: str | None = None
    detector_threshold: float = 0.9

    phash_max_distance: int = 10

    stage_timeout: float = 10.0
    web_stage_timeout: float = 45.0

    trace_dir: str = "traces"
    replay_mode: bool = False
    postgres_url: str | None = None


def load_settings() -> Settings:
    return Settings()
