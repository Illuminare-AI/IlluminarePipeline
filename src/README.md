# Fact-check pipeline (backend)

Developer reference for the Python service in `src/factcheck/`. For what the project is and who it
is for, see the [repository README](../README.md).

For the shorter Windows/Linux setup and the three startup commands, see [Quickstart](../README-QUICKSTART.md).

Multimodal social media fact checker. Takes a post
(image and/or caption) and returns an evidence card. See [`ANALYSIS.md`](../ANALYSIS.md) for known risks and
open decisions.

## Reorganized workspace

- `src/factcheck/`: fact-check backend, port **8000**.
- [frontend](../frontend/README.md): React UI, Vite port **5173**; `/api` proxies to the backend.
- [frontend/image-context](../frontend/image-context/README.md): companion OCR/local vision service, port **8001**.
- [reddit-bot](../reddit-bot/README.md): separate Devvit scaffold and offline runner.
- [extension](../extension/README.md): Chrome extension; right-click text, an image or a page region to check it in the side panel.

The UI now uses the backend's evidence cards. Follow the frontend README for the combined
PowerShell setup. `LLM_BACKEND=fake` remains the default and is labeled in the UI; enable
Anthropic and its key for live model calls. Set `IMAGE_CONTEXT_URL=http://127.0.0.1:8001`
to extract image text automatically through the companion service. Manual `ocr_text` overrides
automatic OCR. OCR failures are reported in `stages.ocr` and other stages continue.

## Hackathon: local Docker backend

```powershell
docker compose up --build -d
cd frontend
npm ci
npm run dev
```

FastAPI runs at `http://127.0.0.1:8000`, with Tesseract OCR and local image descriptions in its companion container on
port 8001. Vite's existing `/api` proxy connects to the published backend port. Compose reads
root `.env` values for model/API configuration; without keys it defaults to the clearly labeled
fake fact-check model. OCR and local vision are enabled between containers; Ollama downloads the image model on first launch. No hosted deployment is needed.

The backend image includes the `db` extra (Postgres store with CPU-only torch for embeddings,
about 1 GB), so setting `POSTGRES_URL` on a deployed container works; without it the in-memory
store is used and traces go to a Docker volume. Build with `--build-arg EXTRAS=` for a slim
image without the store. The container listens on `$PORT` when set (Cloud Run) and on 8000
otherwise. If `POSTGRES_URL` is set but the extra is missing, the service logs a warning and
starts on the in-memory store instead of failing. The local Postgres container is optional
(`docker compose up -d db`).

## Layout

```
src/factcheck/
  models.py        Contracts: Post, Card, ClaimResult, OriginResult, Store protocol
  config.py        Settings from env / .env
  deps.py          Builds the dependency container (real or fake services)
  pipeline.py      check(post, deps) -> Card. Orchestration, timeouts, degradation
  trace.py         Per-check JSON traces and replay mode
  api.py           FastAPI: POST /check, GET /checks/{id}/trace, GET /health
  stages/          One module per stage (s0_fingerprint ... s6_assemble) + runner.py
  llm/             LLM protocol, prompts.py, anthropic_llm.py, fake.py
  services/        fingerprint, factcheck_api, detector, c2pa adapters
  store/memory.py  In-memory Store (default when POSTGRES_URL is empty)
  store/postgres.py  Postgres + pgvector Store: claims, verdicts, media, media_claims tables
tests/             Offline tests using FakeLLM and static service doubles
eval/              cases.jsonl + run_eval.py test harness
```

## Run

```powershell
.\scripts\setup.ps1
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn factcheck.api:app --reload --port 8000
```

Docker uses Python **3.12**. Local development supports Python **3.11 or newer**; the setup script installs
both Python projects, checks native imports and dependency consistency, and preserves an
incompatible `.venv` under `.tmp` before rebuilding it. It uses the current environment's base
Python; use `-PythonPath C:\path\to\python.exe` to select one explicitly (3.12 matches Docker).
Do not recreate an existing environment with a different Python version: compiled packages
such as Pillow must match the interpreter. Always run tests through `.venv\Scripts\python.exe`.

Pass transcribed image text as `ocr_text` (multipart field or JSON key), or configure the
companion OCR service. Stage 1 feeds that text to the model instead of asking it to transcribe.
Send `describe_image=false` when the client already has the post text (the browser extension's
post picker does): OCR and the detector still run on the image, the local vision description is skipped.

Set `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` for real calls. Three models are involved:
`LLM_MODEL` for extraction, claim matching and the cross-claim review, `LLM_SEARCH_MODEL` (default
Sonnet 5.5) for the stage 4 web research loop, which is the slowest call, and `LLM_FAST_MODEL` for
structuring and yes/no checks. `WEB_SEARCH_MAX_USES` caps searches per claim; each one adds a
fetch-and-read round trip, so it is the main latency knob. Add `FACTCHECK_API_KEY`
to enable stage 3 and `DETECTOR_API_KEY` (Walter Writes, `image_detector` scope) to enable the detector. Without them those stages are
marked `skipped` on the card rather than failing.

Set `REVERSE_IMAGE_API_KEY` (a Google API key with the Cloud Vision API enabled) to add a reverse
image search to the origin card. Matches are kept only when they are on reputable domains, the
built-in list in `services/reverse_image.py` or your own `REVERSE_IMAGE_TRUSTED_DOMAINS`. The
search is free for 1,000 images a month; `REVERSE_IMAGE_DAILY_LIMIT` (default 30 per process)
stops it from spending beyond that, after which the card simply omits the search.

## Stage map

| Stage | Module | Status key on card | Skips when |
|---|---|---|---|
| 0 fingerprint | `s0_fingerprint` | `fingerprint` | no image |
| 1 extract | `s1_extract` | `extract` | never |
| 2 memory | `s2_memory` | `memory` | no claims |
| 3 fact-checks | `s3_factcheck` | `fact_check` | memory hit; no API key returns nothing |
| 4 web | `s4_web` | `web` | memory or fact-check hit |
| 5 origin | `s5_origin` | `origin` | never (unavailable without image); reverse search only with a key and budget |
| 6 self-check | `s6_assemble` | `self_check` | only runs on web results |
| 7 consistency | `s7_reconcile` | `consistency` | fewer than two claims, or all settled by fact-checks/memory |

Per-claim stage statuses are merged into one entry per stage: worst state wins, times are summed.

The card also carries a `summary` (`summary.py`): a verdict headline derived in code from the claim
labels, origin status and persuasion tags, shown above the detailed cards. No model call is involved.

Stage 7 reviews all of a post's claims together, since they are researched in isolation. It can
rewrite an explanation in light of what sibling claims established, let a claim cite a sibling's
sources, and change a label. Code enforces that only URLs already on the card can be borrowed,
that `supported`/`refuted` still need two independent domains, that fact-check and memory results
are never changed, and that rewritten explanations pass the stage 6 self-check.

## Postgres store

```bash
pip install -e ".[dev,db]" && docker compose up -d db
# in .env: POSTGRES_URL=postgresql+asyncpg://factcheck:factcheck@localhost:5433/factcheck
```

Tables are created on API startup (`PostgresStore.init_db`). Data model:

| Table | One row per | Holds |
|---|---|---|
| `claims` | distinct claim (case/whitespace-insensitive) | text, 384-d embedding, full-text index, first/last seen |
| `verdicts` | claim per check | label, explanation, sources, disputed spans, evidence origin, persuasion tags, timestamp |
| `media` | checked image | perceptual hash, sha256 file hash, caption, origin signals |
| `media_claims` | image-claim link | which claims an image was checked against |

A check is the set of rows sharing a `check_id`; cards are rebuilt from them. Images are never
stored, and neither are stage timings or raw OCR text. `find_media` matches phash by Hamming
distance; `find_claims` ranks by embedding and returns, per claim, the newest verdict that had
evidence. `find_claims_by_keyword` is full-text search and is not part of the `Store` protocol.

## Eval harness

```bash
.venv/bin/python eval/run_eval.py
```

Add cases to `eval/cases.jsonl`. Include authentic images with `"must_not_accuse": true` so a
false AI accusation fails the run. Re-run after every change to `llm/prompts.py`.
