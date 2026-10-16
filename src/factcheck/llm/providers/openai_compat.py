"""Adapter for any OpenAI-compatible chat-completions endpoint.

One class serves OpenAI itself, Moonshot (Kimi), Ollama, Groq, OpenRouter and Gemini's
compatibility endpoint; the registry picks the base URL, key and the knobs below per provider.
"""
from __future__ import annotations

import base64
from typing import Literal

from pydantic import ValidationError

from .. import telemetry
from ..chat import Capabilities, ChatRequest, ChatResponse, ImagePart, ModelRefusal
from ..schema import parse_json_reply, strict_schema

SchemaMode = Literal["strict", "json_schema", "none"]
"""strict: OpenAI strict structured outputs (post-processed schema). json_schema: the provider
accepts a schema but does not guarantee it (Ollama, Gemini). none: ask for JSON in the prompt."""


class OpenAICompatChat:
    def __init__(
        self,
        model: str,
        client,
        provider: str = "openai",
        schema_mode: SchemaMode = "strict",
        effort_param: str | None = None,
        temperature: float | None = 0.0,
        max_tokens_param: str = "max_tokens",
        supports_images: bool = True,
    ) -> None:
        self.model = model
        self.client = client
        self.provider = provider
        self.schema_mode = schema_mode
        self.effort_param = effort_param
        self.temperature = temperature
        self.max_tokens_param = max_tokens_param
        self.capabilities = Capabilities(
            supports_images=supports_images,
            supports_schema=schema_mode != "none",
            supports_effort=effort_param is not None,
            native_search=False,
        )

    async def complete(self, req: ChatRequest) -> ChatResponse:
        kwargs: dict = {self.max_tokens_param: req.max_tokens}
        if req.schema is not None and self.schema_mode != "none":
            strict = self.schema_mode == "strict"
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": req.schema.__name__,
                    "schema": strict_schema(req.schema) if strict else req.schema.model_json_schema(),
                    "strict": strict,
                },
            }
        if self.effort_param and req.effort and self.capabilities.supports_effort:
            kwargs[self.effort_param] = req.effort
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        messages = [
            {"role": "system", "content": req.system},
            {"role": "user", "content": [_part(p) for p in req.content]},
        ]
        with telemetry.timed_call(self.provider, self.model, req.role, req.op) as rec:
            response = await self.client.chat.completions.create(
                model=self.model, messages=messages, **kwargs
            )
            usage = getattr(response, "usage", None)
            rec.input_tokens = getattr(usage, "prompt_tokens", None)
            rec.output_tokens = getattr(usage, "completion_tokens", None)
            choice = response.choices[0]
            rec.stop_reason = getattr(choice, "finish_reason", None)
            message = choice.message
            if getattr(message, "refusal", None):
                raise ModelRefusal(message.refusal)
            text = message.content or ""
            parsed = None
            if req.schema is not None and self.schema_mode != "none":
                try:
                    parsed = parse_json_reply(text, req.schema)
                except (ValidationError, ValueError):
                    rec.parse_failures = 1  # GenericLLM gets the text and may retry
            return ChatResponse(
                text=text, parsed=parsed, stop_reason=rec.stop_reason,
                input_tokens=rec.input_tokens, output_tokens=rec.output_tokens,
            )


def _part(part) -> dict:
    if isinstance(part, ImagePart):
        data = base64.standard_b64encode(part.data).decode()
        return {"type": "image_url", "image_url": {"url": f"data:{part.media_type};base64,{data}"}}
    return {"type": "text", "text": part}
