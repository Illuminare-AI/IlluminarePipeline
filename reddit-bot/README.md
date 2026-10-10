# Reddit image-context bot scaffold

Mention `u/signal-context-demo` in a comment to extract image context from its containing post. A nested reply still uses the submission, not the immediate parent comment. Missing, deleted/removed and image-less posts produce explicit errors. The scaffold supports direct Reddit images and gallery media, up to four images; it does not follow arbitrary article pages, videos or crosspost chains.

## Local demo (no Reddit account or posting)

Start the [image-context](../frontend/image-context/README.md) service on port 8001, then:

```powershell
cd C:\Github\IlluminarePipeline\reddit-bot
npm install
npm run demo -- --image ..\frontend\demo-preview.png
npm run demo -- --fixture fixtures/no-parent.json
```

The default fixture is fictional and has no image until `--image` is supplied. The runner loads that file, sends its bytes plus the fixture post title/body and mention text to `http://127.0.0.1:8001/analyze`, and prints the reply it would post. It never logs in to Reddit or posts anything. If installed, Tesseract and Ollama perform real OCR and local vision inference. Neither engine is mocked by the demo.

Optional shell variables are in `.env.example`; files aren't loaded automatically. Set `$env:DEMO_INCLUDE_VISION='false'` for OCR only, and `CONTEXT_SERVICE_URL` / `CONTEXT_API_KEY` to match the service. Run the commands in a separate shell from the image server.

## Structure

- `src/core.ts`: explicit mention matching, parent-post validation, analysis orchestration, reply formatting and duplicate protection through injected storage.
- `src/client.ts`: shared HTTP contract with the image service.
- `src/demo.ts` / `fixtures/`: offline runner with a local file or synthetic post.
- `src/server.ts`: Devvit adapter that re-fetches the comment and submission, selects gallery/direct-image media, uses Redis NX claims, and replies as the app.
- `src/live-config.ts`: live integration disabled until configured and approved.
- `devvit.json`: subreddit-scoped comment trigger; no global access or HTTP domain permission requested by default.

## Prepare a Reddit sandbox later

1. Run `npm run build`, then `npm run devvit -- login`. Choose a unique app name in `devvit.json` and match `live-config.ts` to the actual app username.
2. Use a test subreddit you control: `npm run devvit -- playtest YOUR_TEST_SUBREDDIT`. Mention the app under an image post; the default adapter returns `LIVE_NOT_CONFIGURED`. No external calls or local inference run from Reddit by default.
3. For external OCR, arrange an authenticated HTTPS endpoint reachable from Reddit. Reddit-hosted code cannot reach your PC's `localhost`. Request its exact hostname in `devvit.json` under `permissions.http: { "enable": true, "domains": ["your-host.example"] }`. Supply privacy/terms documents and obtain HTTP/app approval. Set a Devvit secret named `CONTEXT_API_KEY`, configure its access as required by the CLI, then set the HTTPS service URL and `externalOcrApproved` in `live-config.ts`.
4. Keep live `includeVision: false`. Reddit's current rules permit listed cloud providers and explicitly disallow self-hosted LLMs. Do not bypass that restriction through an external proxy. An approved cloud-provider adapter or explicit Reddit exception is required to add AI descriptions to the live app. Offline fictional fixtures may use local models freely.
5. Global summon support is a separate approval: request `onMentionInCommentCreate` access, map it to the same internal endpoint, publish an approved version and install it on the app's profile subreddit. The initial scaffold uses ordinary subreddit comment events only.

Local descriptions can take minutes; Devvit fetch has a 30-second limit. The live OCR call uses a 25-second timeout. Before enabling costly/slow live processing, add an asynchronous jobs API plus scheduled result polling instead of holding an event open. Never expose the Ollama port publicly.

## Data and reliability

The bot sends only the selected image URLs, post title/body, mention text and permalink. It stores only trigger IDs/status in Redis for seven days; the image service stores no content. Model output/OCR are labeled as extraction, not fact-checking, and rendered as quoted text. Automated self-mentions and ordinary comments are ignored. Claims are atomic in Redis, but distributed exactly-once posting is not guaranteed: ambiguous posting failures leave a pending claim to avoid duplicates. Check for an existing reply before manually clearing a claim; replies may be retried after the seven-day retention period.

This is a scaffold, not an approved production bot. Before launch, add user/mod opt-outs, abuse controls, deletion handling for any future persistence, moderation appropriate to generated output, cooldowns, failure reconciliation and a support/report channel. Do not retain deleted Reddit content in logs or external storage. No cloud credentials, account registration, public endpoint or publication is created by these files.

## Checks

```powershell
npm run test
npm run build
```

Sources: [Devvit rules](https://developers.reddit.com/docs/devvit_rules), [HTTP fetch restrictions](https://developers.reddit.com/docs/capabilities/server/http-fetch), [mention triggers](https://developers.reddit.com/docs/capabilities/server/global-triggers), [Reddit API](https://developers.reddit.com/docs/capabilities/server/reddit-api).

