# Backend reforms

Planning document for changes to `src/factcheck/`. One section per reform. Decisions that
affect shared contracts (`models.py`, the `Store` protocol, the API response) are called out so
the frontend and store owners can object before code lands.

## 1. LLM-agnostic pipeline

### Goal

Run the same pipeline on different models (Claude, GPT, Gemini, Kimi, Gemma and other open
models through Ollama) and measure which is the most accurate and the fastest. Speed matters
more than cost.

### Decisions taken

- Thin provider adapters, not LiteLLM. The pipeline needs three things from a model: JSON
  output that matches a Pydantic schema, image input, and a bounded tool loop. Those are
  exactly where a general abstraction layer leaks, and two adapters cover every target model.
- Tavily is the client-side search provider for the non-Anthropic path. Its results carry
  extracted page content, which gives the report-writing call real passages to quote.
- The stage-facing `LLM` protocol in `llm/base.py` stays as it is. Stages, the fake backend and
  the tests do not change.
- The `Card` shape does not change. Model identity goes into the trace and `/health`, not the
  card.

### What is provider-specific today

| Concern | Current code | Why it does not port |
|---|---|---|
| Structured output | `messages.parse` with a Pydantic class | OpenAI, Gemini and Ollama each take the schema differently; OpenAI strict mode rejects defaulted fields such as those on `ClaimRevision` |
| Web research | server-side `web_search` tool, `pause_turn` loop, fallbacks beta | the URL allowlist is harvested from Anthropic tool-result blocks; Gemini grounding returns redirect URLs; Ollama models have no search |
| Effort | `output_config.effort`, skipped for Haiku | other providers call this reasoning effort, thinking budget or a think flag |
| Vision | extraction always sends the image | Kimi K2 and several open models are text-only |

### Design

Two abstractions under the existing protocol, one generic implementation on top of them.

**Chat model adapter** (`llm/chat.py` plus `llm/providers/`). One request type: system prompt,
messages, optional images, optional output schema, optional tools, generic effort
(`low | medium | high | None`), max tokens. One response type: text, parsed object when a schema
was given, tool calls, stop reason, and a `CallRecord` (provider, model, role, latency ms,
input and output tokens, retries, parse failures). Adapters:

- `anthropic.py`: the current client, including the native web search tool as an optional
  capability.
- `openai_compat.py`: the `openai` SDK with a configurable base URL. Serves OpenAI, Moonshot
  (Kimi), Ollama's OpenAI endpoint (Gemma and other open models), Groq, OpenRouter, and
  Gemini's OpenAI-compatible endpoint.
- `gemini.py`: native `google-genai` adapter. Deferred; add only if the compatibility endpoint
  turns out to lose schema fidelity or image support.

Each adapter declares capabilities: `supports_images`, `supports_schema` (native JSON schema
mode), `supports_tools`, `supports_effort`, `native_search`.

**Structured output ladder.** Native schema mode where the adapter supports it. Otherwise the
schema is appended to the system prompt as a JSON instruction and the reply is validated with
`model_validate_json`; one repair retry that sends the validation error back. Schemas are
generated once per model class with a post-processing pass that makes every field required and
sets `additionalProperties: false`, so strict providers accept them; optional fields stay
nullable.

**Search provider** (`llm/search.py`). Protocol: `search(query, max_results) -> list[SearchHit]`
where a hit is url, title, snippet or extracted content, published date. Implementations:
`TavilySearch`, and `CachedSearch`, a wrapper that records hits to disk keyed by the normalised
query and replays them. The cache is what makes model comparisons fair: every model sees the
same evidence, and repeated runs cost no quota. Anthropic native search is not a
`SearchProvider`; it is a research mode (below) available only when the search-role model is
the Anthropic adapter.

**Generic pipeline LLM** (`llm/generic_llm.py`). Implements the six protocol methods once,
parameterised by three chat models (judge, fast, search) and a search provider. The current
`anthropic_llm.py` is folded into it: the non-search methods are already provider-neutral prompt
assembly, and the native search loop becomes one research mode.

**Research modes** for stage 4:

- `native`: today's behaviour. Anthropic server-side search, agentic loop, URLs harvested from
  tool-result blocks. Anthropic only.
- `planned`: fixed-depth. One structured call produces two or three queries (at least one
  containing "fact check"). The search provider runs them. One structured call writes the
  `WebEvidence` report from the returned hits. The returned URLs form the allowlist. Two model
  calls regardless of model, no tool calling required, so small open models can run it. This is
  also the speed path.
- `agentic`: client-side tool loop over the search provider, capped by `WEB_SEARCH_MAX_USES`.
  For models with reliable tool calling. Optional; implement after `planned`.

All three feed the same `validate_web_evidence` rules in `stages/s4_web.py`, so the
anti-hallucination guarantees are unchanged.

**Text-only models.** When the extraction-role model lacks image support, the image block is
dropped and the local image description from `card.image_context` (already computed by the
image-context service when present) is passed as text alongside the OCR text. If no description
exists, extraction runs on caption and OCR alone and the trace records that the image was not
seen.

### Configuration

Model settings become provider-prefixed specs resolved by a registry (`llm/registry.py`) that
owns API keys and base URLs.

```
LLM_BACKEND=live            # or fake; "anthropic" accepted as an alias of live
LLM_MODEL=anthropic:claude-opus-5
LLM_FAST_MODEL=anthropic:claude-haiku-4-5
LLM_SEARCH_MODEL=anthropic:claude-sonnet-5-5
RESEARCH_MODE=native        # native | planned | agentic
SEARCH_PROVIDER=tavily      # used by planned and agentic
SEARCH_CACHE_DIR=           # empty disables the record/replay cache

ANTHROPIC_API_KEY=
OPENAI_API_KEY=
OPENAI_BASE_URL=            # optional override
MOONSHOT_API_KEY=           # kimi:
GEMINI_API_KEY=             # gemini:
OLLAMA_URL=http://127.0.0.1:11434   # ollama:
TAVILY_API_KEY=
```

Spec examples: `openai:gpt-5`, `kimi:kimi-k2`, `gemini:gemini-2.5-flash`, `ollama:gemma3:12b`,
`openrouter:moonshotai/kimi-k2`. Timeouts gain per-role overrides because local models are
slower than the current 30 s stage timeout allows.

`/health` adds the three model specs and the research mode. `analysis_mode` on the card stays
`live` for every real backend; the extension and web app need no change.

### Benchmark harness

The goal of the reform is a ranking, and `eval/run_eval.py` cannot produce one today: four
cases, first-claim label only, two cases that accept almost any label.

Additions, in `eval/`:

- `--models` matrix (list of specs applied to all three roles, or a per-role triple),
  `--research-mode`, `--repeat N`, `--out results.jsonl`.
- Per-call telemetry from `CallRecord` written into `trace.json` under a `calls` key, and the
  model specs in the trace header.
- Metrics per model and case: label accuracy against expected labels; claim extraction match
  against an `expected_claims` field with fuzzy matching; source survival rate after the URL
  allowlist (the hallucination rate); self-check sentence drop rate; parse failure and retry
  counts; p50 and p95 latency per stage; tokens per check.
- A case set of 20 to 30 labelled posts with tighter expected labels, at least five authentic
  images with `must_not_accuse`, and two prompt-injection cases.
- Fair-comparison controls: `CachedSearch` frozen before a matrix run, temperature 0 where
  supported, a per-provider concurrency semaphore (Ollama serialises requests, so three
  concurrent claims would otherwise make local models look slower than they are).
- A summary table: one row per model, columns for accuracy, hallucination rate, median check
  wall clock, median stage 4 time.

The local vision model in `frontend/image-context` is a fourth model slot. In the one
successful live trace it took 117 s against 24 s of wall clock for all three web searches, so
the harness should record `VISION_MODEL` and the image-context time alongside the LLM results.

### Order of work

1. Telemetry and harness. Run against the current Anthropic path to record a baseline before
   anything else changes. **Done 2026-10-14**: `llm/telemetry.py` (per-call records and marks
   via a per-check contextvar), trace header with backend and models, `/health` reports them,
   `eval/run_eval.py` rewritten with `--repeat`, `--out`, model overrides and the summary
   metrics, case set grown to 26. Still open from this step: the baseline run itself (needs
   keys and the image-context service up), authentic photo cases for `must_not_accuse`, and
   `--models` as a matrix flag, which waits for the registry in step 3.
2. Chat-model abstraction and the Anthropic adapter. Port the five non-search methods into the
   generic class. Eval must match the baseline. **Done 2026-10-15**: `llm/chat.py` (request,
   response, capabilities, `NativeSearcher`), `llm/providers/anthropic.py` (parse and create
   calls, native search loop), `llm/generic_llm.py` (all six methods, `native` research mode,
   schema ladder with one repair retry). `anthropic_llm.py` removed. Request shapes are pinned by
   `tests/test_anthropic_chat.py`; the ladder by `tests/test_generic_llm.py`.
3. OpenAI-compatible adapter, schema ladder, capability flags, text-only extraction path.
   **Done 2026-10-15**: `llm/providers/openai_compat.py` (one adapter, per-provider knobs for
   schema mode, effort, temperature and the max-tokens parameter name), `llm/schema.py` (strict
   schema post-processor and the JSON reply parser), `llm/registry.py` (provider presets for
   anthropic, openai, kimi, gemini, ollama, groq, openrouter; spec parsing; shared clients;
   text-only model list), settings and env for every provider, `LLM_BACKEND=live` with
   `anthropic` as alias, the `image_description` parameter on `extract` fed from the local
   vision result, and `--models` in the harness. Until step 4 the search role must stay on
   Anthropic, so cross-provider runs pin it with `--search-model`.
4. `SearchProvider` with Tavily, `CachedSearch`, `planned` research mode.
5. Matrix runs. Native Gemini adapter and `agentic` mode only if the results call for them.

### Known gotchas

- `tests/test_anthropic_llm.py` asserts the exact request shape of the native search call. It
  moves with the code to a test of the Anthropic adapter's native mode.
- Replay mode keys cards by post content only. A matrix run with `REPLAY_MODE=true` would
  short-circuit every model after the first. The harness forces replay off.
- The Anthropic fallbacks beta (a refusal re-runs on a substitute model) has no equivalent
  elsewhere. The generic class retries once on refusal with the fast model, then lets the stage
  fail as it does today.
- Gemini grounding URLs are redirects through a Google domain. If a native Gemini adapter is
  added, it must use the `planned` mode with Tavily rather than Gemini's own grounding, or the
  two-independent-domains rule is meaningless.
- OpenAI strict schemas forbid defaults. The schema post-processor handles it, but any new
  Pydantic model with a defaulted field must go through the same path.
