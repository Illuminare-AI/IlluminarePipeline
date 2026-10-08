# Fact-check pipeline (backend)

Backend for the multimodal social media fact checker described in `plan.md`. Takes a post
(image and/or caption) and returns an evidence card. See `ANALYSIS.md` for known risks and
open decisions.

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

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env            # LLM_BACKEND=fake works with no keys
.venv/bin/pytest
.venv/bin/uvicorn factcheck.api:app --reload
curl -F image=@photo.jpg -F caption="Share before it's deleted!" localhost:8000/check
```

OCR is the frontend's job: pass the transcribed image text as `ocr_text` (multipart field or JSON key)
and stage 1 feeds it to the model instead of asking the model to read the image.

Set `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` for real calls. Add `FACTCHECK_API_KEY`
to enable stage 3 and `DETECTOR_API_KEY` (Winston AI) to enable the detector. Without them those stages are
marked `skipped` on the card rather than failing.

## Stage map

| Stage | Module | Status key on card | Skips when |
|---|---|---|---|
| 0 fingerprint | `s0_fingerprint` | `fingerprint` | no image |
| 1 extract | `s1_extract` | `extract` | never |
| 2 memory | `s2_memory` | `memory` | no claims |
| 3 fact-checks | `s3_factcheck` | `fact_check` | memory hit; no API key returns nothing |
| 4 web | `s4_web` | `web` | memory or fact-check hit |
| 5 origin | `s5_origin` | `origin` | never (unavailable without image) |
| 6 self-check | `s6_assemble` | `self_check` | only runs on web results |

Per-claim stage statuses are merged into one entry per stage: worst state wins, times are summed.

## Postgres store

```bash
pip install -e ".[dev,db]" && docker compose up -d
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
