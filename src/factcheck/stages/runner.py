"""Run one stage with a timeout; never raise. Returns (result | None, StageStatus)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import TypeVar

from ..models import StageStatus

T = TypeVar("T")
log = logging.getLogger("factcheck")


async def run_stage(name: str, coro: Awaitable[T], timeout: float) -> tuple[T | None, StageStatus]:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return result, StageStatus(state="ok", ms=_ms(start))
    except TimeoutError:
        log.warning("stage %s timed out after %.1fs", name, timeout)
        return None, StageStatus(state="timeout", ms=_ms(start), detail=f"timed out after {timeout}s")
    except Exception as exc:
        log.exception("stage %s failed", name)
        return None, StageStatus(state="failed", ms=_ms(start), detail=f"{type(exc).__name__}: {exc}")


def skipped(reason: str) -> StageStatus:
    return StageStatus(state="skipped", ms=0, detail=reason)


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
