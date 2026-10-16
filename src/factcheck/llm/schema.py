"""JSON-schema helpers shared by the adapters and GenericLLM."""
from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Keywords strict providers reject or that only constrain what code already enforces.
_DROP = {"default", "title", "minItems", "maxItems", "minLength", "maxLength", "pattern", "format",
         "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """OpenAI strict mode wants every property required and no additional properties, and it
    rejects defaults and length constraints. Pydantic models here use defaults freely, so the
    schema is rewritten: optional fields stay nullable, the model must always emit them."""
    return _strict(model.model_json_schema())


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _strict(v) for k, v in node.items() if k not in _DROP}
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties", {})
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def json_instruction(schema: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object and nothing else: no prose, no code fence. "
        f"It must match this JSON schema exactly:\n{json.dumps(schema.model_json_schema())}"
    )


def parse_json_reply(text: str, schema: type[T]) -> T:
    """Validate a model's text reply as `schema`, tolerating a code fence or surrounding prose."""
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end < start:
            raise ValueError("no JSON object in reply")
        candidate = candidate[start : end + 1]
    return schema.model_validate_json(candidate)
