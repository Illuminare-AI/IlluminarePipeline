"""Per-check trace recording and replay.

Each check writes traces/<check_id>/trace.json containing every stage's input summary and output.
Replay mode keys saved cards by a content hash of the post so demo cases work without network.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import Card, Post, StageStatus


def post_key(post: Post) -> str:
    h = hashlib.sha256()
    h.update(post.image or b"")
    h.update(b"\x00")
    h.update((post.caption or "").strip().lower().encode())
    return h.hexdigest()[:24]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    return value


class Tracer:
    def __init__(self, check_id: str, root: str | Path) -> None:
        self.check_id = check_id
        self.dir = Path(root) / check_id
        self.events: list[dict] = []

    def record(self, stage: str, *, input: Any = None, output: Any = None, error: str | None = None):
        self.events.append(
            {
                "stage": stage,
                "at": datetime.now(UTC).isoformat(),
                "input": _jsonable(input),
                "output": _jsonable(output),
                "error": error,
            }
        )

    def flush(self, card: Card, post: Post) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "trace.json").write_text(
            json.dumps({"check_id": self.check_id, "events": self.events}, indent=2)
        )
        (self.dir / "card.json").write_text(card.model_dump_json(indent=2))
        replay_dir = self.dir.parent / "replay"
        replay_dir.mkdir(parents=True, exist_ok=True)
        (replay_dir / f"{post_key(post)}.json").write_text(card.model_dump_json(indent=2))


def load_trace(root: str | Path, check_id: str) -> dict | None:
    p = Path(root) / check_id / "trace.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_replay(root: str | Path, post: Post) -> Card | None:
    p = Path(root) / "replay" / f"{post_key(post)}.json"
    if not p.exists():
        return None
    card = Card.model_validate_json(p.read_text())
    card.stages["replay"] = StageStatus(state="ok", ms=0, detail="served from saved trace")
    return card
