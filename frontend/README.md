# Signal frontend

The React + TypeScript app sends multipart requests to the root FastAPI fact-check backend. It renders every returned claim, linked evidence, origin signals, persuasion phrases, and incomplete-stage warnings. Backend offline/fake and replay results are clearly labeled.

## Run from the repository root

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn factcheck.api:app --host 127.0.0.1 --port 8000
```

In a separate shell:

```powershell
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000` in development and preview. Copy `frontend/.env.example` to `frontend/.env` to change `BACKEND_URL`. Run `npm run build` for a production bundle, then `npm run preview` to exercise it locally. For static production hosting, configure a same-origin `/api` reverse proxy to FastAPI. Do not put service API keys in frontend environment variables.

## Image text extraction

The backend can request OCR from [image-context](image-context/README.md). Install that package in the root virtual environment and run it on **8001**, leaving **8000** for fact-checking:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ./frontend/image-context
.\.venv\Scripts\python.exe -m uvicorn image_context.api:app --host 127.0.0.1 --port 8001
```

Set `IMAGE_CONTEXT_URL=http://127.0.0.1:8001` in the root `.env`, then restart the fact-check backend. Tesseract must be installed for OCR. If the OCR service requires authentication, set `IMAGE_CONTEXT_API_KEY` on the backend to match the OCR service's `CONTEXT_API_KEY`. OCR requests explicitly disable vision; Ollama is not required for the fact-check flow. Missing/failed OCR is reported while other checks continue. The input form accepts a manual image-text override.

`LLM_BACKEND=fake` is the default: requests run through the backend, but claims are extracted with simple text rules and evidence is simulated. Set `LLM_BACKEND=anthropic` and configure `ANTHROPIC_API_KEY` in the root `.env` for live model calls. Optional fact-check and detector keys are documented there.

## Behavior and data

- Upload, drag, or paste PNG/JPG/WebP up to 10 MB.
- The fictional example sends its transcribed text to the backend; its SVG preview is not uploaded.
- Cancellation aborts the browser request; server work may already have started.
- Images and supplied text are sent to the backend, which can use configured external providers. Checks and text traces may be retained by the backend. Image bytes are not stored by its store implementations.
- Loading is indeterminate; it does not report actual backend stage progress.

## Companion projects

- [image-context](image-context/README.md): local OCR and optional standalone Ollama vision descriptions.
- [reddit-bot](../reddit-bot/README.md): Devvit scaffold and offline demo. Its live adapter remains disabled until configured and approved.
