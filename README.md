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
  store/memory.py  In-memory Store; the Postgres implementation replaces it
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

Set `LLM_BACKEND=anthropic` and `ANTHROPIC_API_KEY` for real calls. Add `FACTCHECK_API_KEY`
to enable stage 3 and `DETECTOR_URL` to enable the detector. Without them those stages are
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

## Plugging in the Postgres store

Implement the three async methods on `Store` in `models.py` and pass the instance to
`Deps.store`. `find_media` should return rows whose phash is within `PHASH_MAX_DISTANCE` bits.
`find_claims` should return the top-k rows by embedding similarity; the pipeline confirms each
candidate with an LLM before reusing anything.

## Eval harness

```bash
.venv/bin/python eval/run_eval.py
```

Add cases to `eval/cases.jsonl`. Include authentic images with `"must_not_accuse": true` so a
false AI accusation fails the run. Re-run after every change to `llm/prompts.py`.
