import hmac
import json
import os
import threading
import httpx

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .models import AnalysisRequest
from .pipeline import analyze_request

app = FastAPI(title="Local Image Context", version="0.1.0")
capacity = threading.BoundedSemaphore(1)


@app.get("/health")
def health():
    return {"status": "ok", "note": "Liveness only; does not verify OCR/model installation."}


@app.post("/analyze")
async def analyze(request: Request):
    key = os.getenv("CONTEXT_API_KEY", "")
    if key and not hmac.compare_digest(request.headers.get("x-api-key", ""), key):
        raise HTTPException(401, "Invalid API key")
    if not capacity.acquire(blocking=False):
        raise HTTPException(429, "Analysis busy; retry later")
    try:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 56_100_000:
                raise HTTPException(413, "Request too large")
        try:
            parsed = AnalysisRequest.model_validate(json.loads(body))
            return await run_in_threadpool(analyze_request, parsed)
        except (ValidationError, ValueError) as exc:
            # Validation errors can contain entire base64 input; never echo them.
            detail = "Invalid analysis request" if isinstance(exc, ValidationError) else str(exc)
            raise HTTPException(422, detail) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Image download unavailable") from exc
    finally:
        capacity.release()
