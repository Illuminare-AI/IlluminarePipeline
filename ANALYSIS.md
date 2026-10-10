# Plan review: risks, roadblocks and decisions taken in the scaffold

## Issues that will bite early

1. **Stage 4 cannot be "one LLM call" if URLs are validated in code.** The plan drops any source
   URL the search tool did not return. The only trustworthy list of returned URLs comes from the
   tool result blocks, which a single structured-output call does not expose cleanly. The scaffold
   uses two calls: a free-text research call with the web search tool (URLs harvested from
   `web_search_tool_result` blocks and citations), then a short structured call that converts the
   report to the schema. Budget 20 to 40 seconds for this stage; the 45 second timeout is tight.

2. **Fact Check Tools API coverage is thin and English-biased.** Expect stage 3 to miss most
   claims that are not already viral. Do not design the demo around it finding things; demo case 1
   should use a claim verified in advance to exist in the index (search the API by hand first).
   Quota is unconfirmed; the adapter returns nothing when the key is absent so the pipeline still runs.

3. **Perceptual hash is fragile to crops.** `phash` survives recompression and resizing well but a
   crop that removes more than roughly 10 to 15 percent of the frame will exceed a Hamming distance
   of 10. Demo case 5 ("cropped and recompressed") should use a light crop, or stage 0 should add a
   second hash (dhash or crop-resistant hashing from `imagehash`) later. The threshold is a setting.

4. **Screenshots break the fingerprint-plus-caption memory rule.** A screenshot carries the
   caption inside the image, so the `caption` field is empty and "caption near-identical" trivially
   matches. Two different screenshots of the same photo with different overlaid text will not hash
   alike, so this is mostly a false-negative risk, not a false reuse risk. OCR text could be
   included in the memory key later.

5. **Detectors are unreliable on platform-processed images, and the false-accusation cost is the
   highest in the project.** The scaffold uses a high threshold (0.9), names the detector, and never
   lets the origin result touch the claim label. The "no signal found" note explicitly says it is not
   verification. The detector is Walter Writes (`WalterWritesDetector`); the emitted score is
   `P(fake) + P(inpainting)`, so a real photo with AI-edited regions counts as a signal too.

6. **C2PA will almost never be present on social media images.** Platforms strip metadata on
   upload. Expect credentials only on demo images you generate yourself with a tool that signs
   them (Adobe Firefly, some DALL-E exports). `c2pa-python` is an optional dependency and its API has
   shifted between versions; the reader returns None on any failure.

7. **Prompt injection via OCR text and search results.** Captions and page content are untrusted.
   The prompts state this, but structural defences matter more: claims are rewritten before any
   search, disputed spans are validated as substrings, and URLs are validated against tool results.
   Never pass raw caption text into the search prompt (the plan says this; the scaffold enforces it
   by only passing the normalised claim).

8. **Latency stacks per claim.** Three claims with no memory or fact-check hit means three web
   searches and three self-checks in sequence. The scaffold processes claims sequentially for
   simplicity; switching `_resolve_claims` to `asyncio.gather` per claim is a small change once the
   provider rate limits are known. Stage 5 already runs concurrently with the claim stages.

9. **Memory reuse of "not enough evidence".** Reusing an old inconclusive verdict is wrong when new
   evidence may exist. The scaffold skips candidates whose evidence origin is `none` but still
   reuses `not_enough_evidence` results that came from a real search. Decide on a TTL.

10. **The self-check has nothing to check against for fact-check-API results.** Those explanations
    are templated from the publisher rating, so stage 6 is skipped for them. For web results with no
    surviving quotes, the scaffold keeps only the first sentence.

## Proposed solutions

Numbered to match the issues above. Where two paths are reasonable, the first is the recommended one.

1. **Stage 4 as two calls.** Keep the two-call design and make it cheaper: run the research call at
   low effort with a cap of four searches, and give the structuring call a 256-token budget. If latency
   is still a problem, pass the raw tool-result blocks straight into the structuring call and skip the
   free-text report. Raise the stage timeout to 60 seconds and cap extraction at two claims for the demo.

2. **Thin Fact Check API coverage.** Treat stage 3 as a bonus, not a dependency. Pre-select demo
   case 1 by querying the API by hand and picking a claim it already indexes. Later, add a second
   provider behind the same adapter (for example ClaimReview markup from an allowlist of fact-checker
   sites). Cache every API response on disk so repeat runs cost no quota.

3. **Perceptual hash fails on crops.** Store two hashes per image, the current phash and the
   crop-resistant hash from the imagehash library, and match on either. Keep the demo crop under ten
   percent and tune `PHASH_MAX_DISTANCE` with the eval harness over a folder of cropped and
   recompressed variants. Longer term, a small vision-model embedding handles crops and overlays
   better than any hash.

4. **Screenshots have no caption.** Include OCR text in the memory key: compare the candidate's
   stored OCR text with the new post's OCR text using the same near-identical rule applied to
   captions. This means splitting stage 0 into "image match" and "confirm with text", with the second
   half running after extraction when the caption is empty.

5. **Detector false accusations.** Keep the high threshold and add two guards: require a second
   independent signal (a second detector, or EXIF data missing where the platform would preserve it)
   before showing "possible AI signal", and always render the score and detector name on the card.
   Add at least five authentic images to the eval set with `must_not_accuse` so any threshold change
   that produces an accusation fails the run.

6. **C2PA rarely present.** Design the demo around it: generate demo case 3's image with a tool that
   signs credentials and confirm the manifest survives the upload path by running the reader on the
   exact file the page sends. Show "no credentials found" as neutral information with a one-line note
   that most platforms strip them.

7. **Prompt injection.** Keep the structural defences and add delimiters around all untrusted text in
   every prompt, stating that anything inside them is quoted material. Add two injection cases to the
   eval set (instructions hidden in the caption, and in a search result) and assert that label,
   sources and disputed spans are unaffected.

8. **Latency stacks per claim.** Process claims concurrently in `_resolve_claims` with a semaphore
   of two or three, and add a client-side rate limiter so concurrent calls do not trip provider
   limits. Cap extraction at two claims for the demo.

9. **Stale inconclusive verdicts in memory.** Store a timestamp with each saved check. Give
   `not_enough_evidence` a short time to live (about 24 hours) and supported or refuted a longer one.
   When memory returns a stale inconclusive result, fall through to stages 3 and 4 but keep the old
   sources as a starting point.

10. **Self-check has nothing to check for fact-check results.** Fetch the review page and use its
    first paragraph as the quote so stage 6 has material. If fetching is not acceptable, keep the
    templated explanation, since every word comes from the publisher's rating. For web results with
    no surviving quotes, downgrade the label to `not_enough_evidence` rather than keeping a bare
    sentence.

Cross-cutting: commit real-run traces for the five demo cases as soon as keys arrive so replay mode
is a working fallback from day one, and make `eval/run_eval.py` the gate for every prompt or
threshold change, since several of these fixes trade one error type for another.

## Contract decisions made (confirm with teammates)

- `Store` methods are `async`. Postgres access through asyncpg or SQLAlchemy async fits the
  pipeline; a sync driver would block the event loop.
- Card label values are snake_case strings: `supported`, `refuted`, `missing_context`,
  `not_enough_evidence`. "Nothing checkable" is represented by an empty `claims` list and
  `extract` stage `ok`. Origin status values: `credentials_present`, `possible_ai_signal`,
  `no_signal_found`, `unavailable`. The frontend maps these to display wording (open item 4).
- Per-claim stage statuses are merged into one status per stage on the card. If the page wants
  per-claim timing, add a `stages` field to `ClaimResult`.
- `POST /check` accepts multipart form data (`image`, `caption`, `source_url`) or JSON with
  `image_base64`. Max image size 10 MB.
- Trace files live under `TRACE_DIR/<check_id>/` and replay files under `TRACE_DIR/replay/`,
  keyed by a hash of image bytes and normalised caption. Replay mode only serves exact matches.

## Not yet implemented (deliberate stubs)

- Real Postgres store (teammate).
- Embedding-based `find_claims`; the in-memory store uses token overlap.
- LettuceDetect as an alternative self-checker.
- Per-claim concurrency and a rate limiter for the LLM client.
- Auth, CORS and request logging on the API (add CORS before the frontend connects).

## Before the demo

- Run `eval/run_eval.py` with `LLM_BACKEND=anthropic` on all five demo cases and commit the
  traces, then switch on `REPLAY_MODE` as the fallback.
- Tune `PHASH_MAX_DISTANCE` on the actual cropped demo image.
- Verify the Fact Check Tools key and quota with a hand query before relying on demo case 1.
