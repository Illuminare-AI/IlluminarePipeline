"""Dependency container. Build one per process; tests build their own with fakes."""
from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, load_settings
from .llm.base import LLM
from .models import Store
from .services.c2pa import C2paReader, CredentialsReader
from .services.detector import Detector, HttpDetector, NullDetector
from .services.factcheck_api import FactCheckClient, GoogleFactCheckClient, NullFactCheckClient
from .store.memory import InMemoryStore


@dataclass
class Deps:
    settings: Settings
    store: Store
    llm: LLM
    factcheck: FactCheckClient
    detector: Detector
    credentials: CredentialsReader


def build_deps(settings: Settings | None = None) -> Deps:
    s = settings or load_settings()

    store: Store
    if s.postgres_url:
        from .store.postgres import PostgresStore

        store = PostgresStore(
            db_url=s.postgres_url,
            phash_max_distance=s.phash_max_distance,
        )
    else:
        store = InMemoryStore(phash_max_distance=s.phash_max_distance)

    if s.llm_backend == "anthropic":
        from .llm.anthropic_llm import AnthropicLLM

        llm: LLM = AnthropicLLM(model=s.llm_model, api_key=s.anthropic_api_key)
    else:
        from .llm.fake import FakeLLM

        llm = FakeLLM()

    factcheck: FactCheckClient = (
        GoogleFactCheckClient(s.factcheck_api_key, s.factcheck_url)
        if s.factcheck_api_key
        else NullFactCheckClient()
    )

    detector: Detector = (
        HttpDetector(s.detector_url, s.detector_api_key, s.detector_threshold)
        if s.detector_url
        else NullDetector()
    )

    return Deps(
        settings=s,
        store=store,
        llm=llm,
        factcheck=factcheck,
        detector=detector,
        credentials=C2paReader(),
    )