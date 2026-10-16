"""Per-call LLM telemetry for the trace and the benchmark harness.

A `Collector` is activated for the duration of one check (a contextvar, so concurrent checks and
the tasks a check spawns each see their own). Backends call `record_call` after every model
request; stages call `mark` for code-side measurements such as how many sources survived
validation. Both are no-ops when no collector is active, so unit tests of a single function need
no setup.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from typing import Any

Role = str  # "judge" | "fast" | "search"


@dataclass
class CallRecord:
    provider: str
    model: str
    role: Role
    op: str
    """Protocol method that made the call: extract, same_claim, web_evidence, ..."""
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    error: str | None = None
    retries: int = 0
    parse_failures: int = 0


@dataclass
class Collector:
    calls: list[CallRecord] = field(default_factory=list)
    marks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"calls": [asdict(c) for c in self.calls], "marks": list(self.marks)}


_current: ContextVar[Collector | None] = ContextVar("factcheck_telemetry", default=None)


def current() -> Collector | None:
    return _current.get()


def activate(collector: Collector | None = None) -> tuple[Collector, Token]:
    collector = collector or Collector()
    return collector, _current.set(collector)


def deactivate(token: Token) -> None:
    _current.reset(token)


def record_call(record: CallRecord) -> None:
    col = _current.get()
    if col is not None:
        col.calls.append(record)


def mark(kind: str, **fields: Any) -> None:
    col = _current.get()
    if col is not None:
        col.marks.append({"kind": kind, **fields})


@contextmanager
def timed_call(provider: str, model: str, role: Role, op: str) -> Iterator[CallRecord]:
    """Measure one request. The caller fills in tokens and stop reason on the yielded record;
    an exception is recorded as the error and re-raised."""
    rec = CallRecord(provider=provider, model=model, role=role, op=op, latency_ms=0)
    start = time.perf_counter()
    try:
        yield rec
    except BaseException as exc:
        rec.error = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        rec.latency_ms = int((time.perf_counter() - start) * 1000)
        record_call(rec)
