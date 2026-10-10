"""Dependency container. Build one per process; tests build their own with fakes."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings, load_settings
from .llm.base import LLM
from .models import Store
from .services.c2pa import C2paReader, CredentialsReader
from .services.detector import Detector, NullDetector, WalterWritesDetector
from .services.factcheck_api import FactCheckClient, GoogleFactCheckClient, NullFactCheckClient
from .services.reverse_image import (
    GoogleVisionReverseImageSearch,
    NullReverseImageSearch,
    ReverseImageSearch,
    parse_trusted_domains,
)
from .store.memory import InMemoryStore


@dataclass
class Deps:
    settings: Settings
    store: Store
    llm: LLM
    factcheck: FactCheckClient
    detector: Detector
    credentials: CredentialsReader
    reverse_image: ReverseImageSearch = field(default_factory=NullReverseImageSearch)


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

        llm: LLM = AnthropicLLM(
            model=s.llm_model, api_key=s.anthropic_api_key, fast_model=s.llm_fast_model
        )
    else:
        from .llm.fake import FakeLLM

        llm = FakeLLM()

    factcheck: FactCheckClient = (
        GoogleFactCheckClient(s.factcheck_api_key, s.factcheck_url)
        if s.factcheck_api_key
        else NullFactCheckClient()
    )

    detector: Detector = (
        WalterWritesDetector(
            api_key=s.detector_api_key,
            url=s.detector_url,
            threshold=s.detector_threshold,
        )
        if s.detector_api_key
        else NullDetector()
    )

    reverse_image: ReverseImageSearch = (
        GoogleVisionReverseImageSearch(
            api_key=s.reverse_image_api_key,
            url=s.reverse_image_url,
            trusted_domains=parse_trusted_domains(s.reverse_image_trusted_domains),
            daily_limit=s.reverse_image_daily_limit,
        )
        if s.reverse_image_api_key
        else NullReverseImageSearch()
    )

    return Deps(
        settings=s,
        store=store,
        llm=llm,
        factcheck=factcheck,
        detector=detector,
        credentials=C2paReader(),
        reverse_image=reverse_image,
    )