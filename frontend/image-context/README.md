# Local image context

Standalone Python service and CLI for image OCR and local vision descriptions. No paid APIs, Reddit credentials, cloud model, or training required. Keep downloaded models local; compute, storage and electricity still have costs.

## Setup (PowerShell)

```powershell
cd C:\Github\IlluminarePipeline\frontend\image-context
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

`requirements-lock.txt` captures the exact dependencies verified in this workspace. To reproduce them, install with `pip install -r requirements-lock.txt` before installing this project with `pip install --no-deps -e .`.

Install [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html) with English language data. If it is not on PATH:

```powershell
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
```

Install [Ollama](https://ollama.com/download), then download a vision model:

```powershell
ollama pull qwen3-vl:4b
$env:VISION_MODEL = 'qwen3-vl:4b'
```

The 4B tag is a practical starting point, not a hardware guarantee; the model is several GB and requires additional memory at runtime. CPU inference works but can be slow. Try `qwen3-vl:2b` on a smaller machine. Model downloads need internet; local file analysis does not after installation. Check the model license before redistribution.

```powershell
.\.venv\Scripts\python.exe -m uvicorn image_context.api:app --host 127.0.0.1 --port 8001
```

In a separate shell, run the CLI (does not require the HTTP server):

```powershell
.\.venv\Scripts\image-context.exe ..\demo-preview.png --context 'Demo screenshot'
.\.venv\Scripts\image-context.exe ..\demo-preview.png --no-vision
```

`.env.example` documents configuration. It is not automatically loaded: set environment variables in PowerShell before launching. Set `VISION_ENABLED=false` for OCR-only operation.

## HTTP contract

`POST /analyze`, JSON; optional `X-API-Key` when `CONTEXT_API_KEY` is configured:

```json
{
  "images": [{"url": "https://i.redd.it/your-image.png"}],
  "context": {"title": "Post title", "body": "Post text", "request": "Describe this"},
  "include_vision": true
}
```

Alternatively each image can have `base64` containing raw image bytes encoded as base64 (no data-URL prefix). Exactly one of `url`/`base64` per image. Up to four images, 10 MiB each, 20 megapixels each. URL fetches permit only exact HTTPS media hosts in `IMAGE_ALLOWED_HOSTS`; no redirects. Do not add arbitrary/user-controlled domains to that list. Animated images use the first frame only.

Response `schema_version: "1.0"` includes supplied context, metadata (dimensions, format, hash), OCR text, per-word confidence and bounding boxes in normalized image pixels, two independent OCR passes, structured vision observations (scene, objects, layout, additional visible text, visible claims, uncertainties), warnings and limitations. EXIF device/location data is deliberately excluded. The model sees OCR plus the image and contextual text. It receives bounded image resolution; full-resolution OCR is separate.

OCR and vision failures produce explicit `unavailable` statuses with remaining results preserved. A disabled model produces `disabled`. `GET /health` checks server liveness only. No content is stored by this service; returned JSON may contain sensitive visible text. Ollama has its own runtime/logging behavior. Descriptions are observations, not provenance or fact-checking. OCR confidence is engine confidence, not calibrated truth probability.

For public hosting, put authentication/TLS and request-rate limits in front of this service, set `CONTEXT_API_KEY`, and keep Ollama on loopback. Only one analysis runs at a time; concurrent requests return 429. This is a local prototype, not a production deployment.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests exercise image validation, URL restrictions, OCR pass structure, Ollama request/response format, authentication and degraded operation. They stub OCR/model execution; real engine quality must be checked after installation.

## Reddit distinction

Use the local model for standalone/offline demos. Reddit currently disallows self-hosted LLMs in Devvit apps. The [Reddit bot](../../reddit-bot/README.md)'s live adapter requests OCR only and starts disabled; model inference on live Reddit content requires a permitted provider or explicit written exception. [Devvit rules](https://developers.reddit.com/docs/devvit_rules).

