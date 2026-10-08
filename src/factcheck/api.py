"""FastAPI app. POST /check accepts multipart (image + caption) or JSON with base64 image."""
from __future__ import annotations

import base64
import logging

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from .deps import Deps, build_deps
from .models import Card, Post
from .pipeline import check
from .trace import load_trace

logging.basicConfig(level=logging.INFO)

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class CheckJson(BaseModel):
    image_base64: str | None = None
    caption: str | None = None
    source_url: str | None = None


def create_app(deps: Deps | None = None) -> FastAPI:
    app = FastAPI(title="Fact-check pipeline", version="0.1.0")
    app.state.deps = deps or build_deps()

    @app.get("/health")
    async def health():
        s = app.state.deps.settings
        return {"ok": True, "llm_backend": s.llm_backend, "replay_mode": s.replay_mode}

    @app.post("/check", response_model=Card)
    async def check_multipart(
        request: Request,
        image: UploadFile | None = File(default=None),
        caption: str | None = Form(default=None),
        source_url: str | None = Form(default=None),
    ):
        if request.headers.get("content-type", "").startswith("application/json"):
            body = CheckJson.model_validate(await request.json())
            data = base64.b64decode(body.image_base64) if body.image_base64 else None
            post = Post(image=data, caption=body.caption, source_url=body.source_url)
        else:
            data = await image.read() if image is not None else None
            post = Post(image=data or None, caption=caption, source_url=source_url)
        if post.image and len(post.image) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "image too large")
        if not post.image and not (post.caption or "").strip():
            raise HTTPException(400, "provide an image, a caption, or both")
        return await check(post, app.state.deps)

    @app.get("/checks/{check_id}/trace")
    async def get_trace(check_id: str):
        trace = load_trace(app.state.deps.settings.trace_dir, check_id)
        if trace is None:
            raise HTTPException(404, "unknown check id")
        return trace

    return app


app = create_app()
