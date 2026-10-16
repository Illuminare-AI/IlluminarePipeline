from factcheck.llm.schema import parse_json_reply, strict_schema
from factcheck.models import ExtractionOutput, ReconcileOutput, SameClaimVerdict


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_strict_schema_requires_every_field_and_closes_objects():
    schema = strict_schema(ReconcileOutput)
    assert schema["required"] == ["revisions"] and schema["additionalProperties"] is False
    revision = schema["$defs"]["ClaimRevision"]
    assert set(revision["required"]) == set(revision["properties"])
    assert revision["additionalProperties"] is False
    for node in _walk(schema):
        assert "default" not in node and "title" not in node
    # nullable optional fields stay nullable
    assert any(n.get("type") == "null" for n in _walk(revision["properties"]["label"]))


def test_strict_schema_drops_length_constraints_but_keeps_descriptions():
    schema = strict_schema(ExtractionOutput)
    assert "maxItems" not in schema["properties"]["claims"]
    assert "description" in schema["$defs"]["Tactic"]["properties"]["phrase"]


def test_parse_json_reply_tolerates_prose_and_fences():
    assert parse_json_reply('Here: {"same": true}. Done.', SameClaimVerdict).same is True
    assert parse_json_reply('```\n{"same": false}\n```', SameClaimVerdict).same is False
