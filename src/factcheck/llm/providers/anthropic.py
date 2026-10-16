"""Anthropic adapter: structured output through `messages.parse`, and the server-side web
search tool as the native research loop."""
from __future__ import annotations

import base64

import anthropic

from .. import telemetry
from ..chat import (
    Capabilities,
    ChatRequest,
    ChatResponse,
    ImagePart,
    ModelRefusal,
    ResearchResult,
)

WEB_SEARCH_TOOL = "web_search_20260209"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def supports_effort(model: str) -> bool:
    """Haiku 4.5 rejects the `effort` parameter."""
    return not model.startswith("claude-haiku-4")


class AnthropicChat:
    provider = "anthropic"

    def __init__(
        self,
        model: str,
        client: anthropic.AsyncAnthropic | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.client = client or (
            anthropic.AsyncAnthropic(api_key=api_key) if api_key else anthropic.AsyncAnthropic()
        )
        self.capabilities = Capabilities(
            supports_images=True,
            supports_schema=True,
            supports_effort=supports_effort(model),
            native_search=True,
        )

    async def complete(self, req: ChatRequest) -> ChatResponse:
        kwargs: dict = {}
        if req.effort and self.capabilities.supports_effort:
            kwargs["output_config"] = {"effort": req.effort}
        messages = [{"role": "user", "content": [_block(p) for p in req.content]}]
        with telemetry.timed_call(self.provider, self.model, req.role, req.op) as rec:
            if req.schema is not None:
                response = await self.client.messages.parse(
                    model=self.model,
                    max_tokens=req.max_tokens,
                    system=req.system,
                    messages=messages,
                    output_format=req.schema,
                    **kwargs,
                )
            else:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=req.max_tokens,
                    system=req.system,
                    messages=messages,
                    **kwargs,
                )
            _fill_usage(rec, response)
            if response.stop_reason == "refusal":
                raise ModelRefusal("model refused the request")
            return ChatResponse(
                text="".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text"),
                parsed=getattr(response, "parsed_output", None),
                stop_reason=response.stop_reason,
                input_tokens=rec.input_tokens,
                output_tokens=rec.output_tokens,
            )

    async def research(self, system: str, claim: str, max_uses: int) -> ResearchResult:
        """Free-text research call with the server-side search tool. URLs are harvested from the
        tool-result blocks and citations, never from the model's prose. The beta `fallbacks`
        option re-runs a safety refusal on a substitute model server-side."""
        messages: list[dict] = [{"role": "user", "content": f"Claim: {claim}"}]
        returned_urls: set[str] = set()
        report_parts: list[str] = []
        for _ in range(5):  # pause_turn restarts
            with telemetry.timed_call(self.provider, self.model, "search", "web_evidence") as rec:
                response = await self.client.beta.messages.create(
                    model=self.model,
                    max_tokens=16000,
                    system=system,
                    messages=messages,
                    tools=[{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses}],
                    output_config={"effort": "low"},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                )
                _fill_usage(rec, response)
            for block in response.content:
                btype = getattr(block, "type", "")
                if btype == "fallback":
                    continue  # a substitute model took over after a refusal; the content follows
                if btype == "web_search_tool_result":
                    results = getattr(block, "content", None)
                    if isinstance(results, list):  # an error result is an object, not a list
                        for item in results:
                            url = getattr(item, "url", None)
                            if url:
                                returned_urls.add(url)
                elif btype == "text":
                    report_parts.append(block.text)
                    for cit in getattr(block, "citations", None) or []:
                        url = getattr(cit, "url", None)
                        if url:
                            returned_urls.add(url)
            if response.stop_reason == "refusal":
                raise ModelRefusal("model refused the request")
            if response.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": response.content})
        return ResearchResult(report="\n".join(report_parts).strip(), returned_urls=returned_urls)


def _block(part) -> dict:
    if isinstance(part, ImagePart):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": part.media_type,
                "data": base64.standard_b64encode(part.data).decode(),
            },
        }
    return {"type": "text", "text": part}


def _fill_usage(rec: telemetry.CallRecord, response) -> None:
    usage = getattr(response, "usage", None)
    rec.input_tokens = getattr(usage, "input_tokens", None)
    rec.output_tokens = getattr(usage, "output_tokens", None)
    rec.stop_reason = getattr(response, "stop_reason", None)
