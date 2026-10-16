"""Provider-neutral chat model interface.

One request type, one response type, one method. Provider adapters in `llm/providers/` translate
these to their SDK and declare what they can do through `Capabilities`. `GenericLLM` builds the
pipeline's six protocol methods on top, so a new provider is one adapter, not a new backend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

Effort = Literal["low", "medium", "high"] | None
Role = Literal["judge", "fast", "search"]


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    media_type: str


Part = str | ImagePart


@dataclass
class ChatRequest:
    system: str
    content: list[Part]
    """One user turn: text parts and image parts in order."""
    schema: type[BaseModel] | None = None
    """When set, the response must carry `parsed`, an instance of this model."""
    effort: Effort = None
    max_tokens: int = 4096
    role: Role = "judge"
    op: str = ""
    """Protocol method making the call; recorded in telemetry."""


@dataclass
class ChatResponse:
    text: str = ""
    parsed: BaseModel | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class Capabilities:
    supports_images: bool = True
    supports_schema: bool = True
    """Native JSON-schema output. Without it, GenericLLM asks for JSON in the prompt and parses."""
    supports_effort: bool = True
    native_search: bool = False
    """The provider can run a server-side web search loop (`NativeSearcher`)."""


@runtime_checkable
class ChatModel(Protocol):
    provider: str
    model: str
    capabilities: Capabilities

    async def complete(self, req: ChatRequest) -> ChatResponse: ...


@dataclass
class ResearchResult:
    report: str
    returned_urls: set[str] = field(default_factory=set)
    """Every URL the search tool actually returned; the allowlist for cited sources."""


@runtime_checkable
class NativeSearcher(Protocol):
    """A chat model with a provider-side search tool (today: Anthropic)."""

    async def research(self, system: str, claim: str, max_uses: int) -> ResearchResult: ...


class ModelRefusal(RuntimeError):
    """The model declined the request. Stages treat it like any other failure."""
