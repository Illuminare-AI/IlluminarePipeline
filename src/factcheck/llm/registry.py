"""Resolve a model spec such as `anthropic:claude-opus-5` or `ollama:gemma3:12b` to an adapter.

The provider prefix selects a preset: which SDK, base URL, key setting and the structured-output
mode the endpoint honours. A spec with no prefix is accepted for Claude models only, so older
`.env` files keep working.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..config import Settings
from .chat import ChatModel

Kind = Literal["anthropic", "openai"]
SchemaMode = Literal["strict", "json_schema", "none"]


@dataclass(frozen=True)
class Preset:
    kind: Kind
    key_setting: str | None = None
    """Settings attribute holding the API key; None when the endpoint needs none."""
    base_url: str | None = None
    """Fixed base URL; None means the SDK default or a settings override."""
    schema_mode: SchemaMode = "strict"


PRESETS: dict[str, Preset] = {
    "anthropic": Preset("anthropic", "anthropic_api_key"),
    "openai": Preset("openai", "openai_api_key"),
    "kimi": Preset("openai", "moonshot_api_key", "https://api.moonshot.ai/v1", "none"),
    "gemini": Preset(
        "openai", "gemini_api_key", "https://generativelanguage.googleapis.com/v1beta/openai/", "json_schema"
    ),
    "ollama": Preset("openai", None, None, "json_schema"),
    "groq": Preset("openai", "groq_api_key", "https://api.groq.com/openai/v1", "none"),
    "openrouter": Preset("openai", "openrouter_api_key", "https://openrouter.ai/api/v1", "none"),
}

# Models known to take no image input. Extraction then gets the local description instead.
TEXT_ONLY_PREFIXES = ("kimi-k2", "deepseek", "gpt-oss")

_REASONING = re.compile(r"^(gpt-5|o\d)")
"""OpenAI models that take `reasoning_effort` and reject `temperature`."""


def parse_spec(spec: str) -> tuple[str, str]:
    spec = spec.strip()
    provider, sep, model = spec.partition(":")
    if sep and provider in PRESETS:
        if not model:
            raise ValueError(f"model spec {spec!r} has no model after the provider prefix")
        return provider, model
    if spec.startswith("claude"):
        return "anthropic", spec
    raise ValueError(
        f"model spec {spec!r} needs a provider prefix, one of: {', '.join(sorted(PRESETS))}"
    )


class ModelRegistry:
    """Builds adapters, sharing one SDK client per provider endpoint."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._clients: dict[str, object] = {}
        extra = [m.strip() for m in settings.llm_text_only_models.split(",") if m.strip()]
        self.text_only_prefixes = TEXT_ONLY_PREFIXES + tuple(extra)

    def build(self, spec: str) -> ChatModel:
        provider, model = parse_spec(spec)
        preset = PRESETS[provider]
        if preset.kind == "anthropic":
            from .providers.anthropic import AnthropicChat

            return AnthropicChat(model, client=self._anthropic_client())

        from .providers.openai_compat import OpenAICompatChat

        reasoning = provider == "openai" and bool(_REASONING.match(model))
        return OpenAICompatChat(
            model,
            client=self._openai_client(provider, preset),
            provider=provider,
            schema_mode=preset.schema_mode,
            effort_param="reasoning_effort" if reasoning else None,
            temperature=None if reasoning else 0.0,
            max_tokens_param="max_completion_tokens" if provider == "openai" else "max_tokens",
            supports_images=not model.startswith(self.text_only_prefixes),
        )

    def _key(self, provider: str, preset: Preset) -> str | None:
        if preset.key_setting is None:
            return None
        key = getattr(self.s, preset.key_setting)
        if not key and provider != "anthropic":  # the Anthropic SDK also reads its own env var
            raise ValueError(
                f"provider {provider!r} needs {preset.key_setting.upper()} in the environment"
            )
        return key

    def _anthropic_client(self):
        if "anthropic" not in self._clients:
            import anthropic

            key = self._key("anthropic", PRESETS["anthropic"])
            self._clients["anthropic"] = (
                anthropic.AsyncAnthropic(api_key=key, timeout=self.s.llm_request_timeout)
                if key else anthropic.AsyncAnthropic(timeout=self.s.llm_request_timeout)
            )
        return self._clients["anthropic"]

    def _openai_client(self, provider: str, preset: Preset):
        if provider not in self._clients:
            import openai

            if provider == "ollama":
                base_url, key = self.s.ollama_url.rstrip("/") + "/v1", "ollama"
            else:
                base_url = preset.base_url or (self.s.openai_base_url if provider == "openai" else None)
                key = self._key(provider, preset)
            self._clients[provider] = openai.AsyncOpenAI(
                api_key=key, base_url=base_url, timeout=self.s.llm_request_timeout
            )
        return self._clients[provider]
