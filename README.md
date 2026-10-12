# Luminate: A little context before you share

Luminate provides instant context for social media posts, right where you read them. Right-click a post in Chrome or drop a screenshot into the web app. In the time it takes to read the comments, Luminate delivers a source-backed verdict, analyzes the image's origin (including AI generation signals), and flags persuasion tactics used in the text.

**Demo video (2–3 minutes):** [video](https://youtu.be/gPryaq86BUY)

## The problem we are solving

Fact-checks on social media posts arrive too late. By the time a community note or debunk appears, most users have already scrolled past. This is a major issue, given that over 53% of US adults get some of their news from social media.[^1]

In addition, this delay has two consequences: false posts spread unchallenged, while authentic photos and quotes are dismissed as "likely AI" because readers lack a quick way to verify them.

Luminate moves verification to the moment of reading. It allows people to stay informed without leaving their feed and ensures human-made content gets a fair hearing instead of blanket suspicion.

## Who it's for

- **People scrolling a feed** who want to know if a post holds up in under a minute—before they share or argue about it.
- **Moderators and small newsrooms** who receive screenshots all day and need a rapid first pass with attached sources.
- **Developers** looking for a working, inspectable fact-check pipeline. Every stage writes a trace, the LLM interface is just five methods, and a fake model backend allows the entire system to run offline.

## What's in this repository

Everything below is built and running today:

- **Chrome Extension** ([`extension/`](extension/README.md)): Adds context-menu entries to check a post, selected text, an image, or a region. It outlines the post, extracts the text and main photo directly from the DOM (skipping server-side OCR), strips irrelevant metadata, and displays results in Chrome's side panel.
- **Web App** ([`frontend/`](frontend/README.md)): Built for screenshots. Drop or paste an image, add optional context, and get an evidence card. Includes accessibility settings and a fictional sandbox post to test the system.
- **Fact-Check Backend** ([`src/`](src/README.md)): A FastAPI service that processes a post into an evidence card. One request, one JSON response, no login required.
- **Local Image Service** ([`frontend/image-context/`](frontend/image-context/README.md)): Runs Tesseract OCR and a local vision model via Ollama. Image text and descriptions never leave your machine.
- **Reddit Bot Scaffold** ([`reddit-bot/`](reddit-bot/README.md)): A Devvit bot triggered by mentions. Runs end-to-end offline against fixtures (live integration is wired but pending app approval).
- **Deployment & Evals**: Includes Docker/Compose files for the backend, image service, Ollama, and Postgres, plus an [eval harness](eval/run_eval.py) with regression cases.

## How it works

A check is processed through a pipeline of specialized, time-boxed stages. If a service is slow or missing, that specific section gracefully degrades rather than failing the entire check.

1. **Ingest:** The extension reads text and photos directly from the page. For screenshots, the local image service transcribes text and describes the visual.
2. **Fingerprint:** The image is hashed perceptually and checked against memory. If previously checked (even if re-cropped or compressed), the stored card is returned instantly.
3. **Extract Claims:** The model extracts up to three factual, standalone statements. It also tags persuasion techniques (urgency, authority, fear, promised reward) using the exact triggering phrases. Post metadata (views, timestamps) is ignored.
4. **Research (Concurrent):**
   - **Memory:** Reuses stored verdicts only if the model confirms the claim matches exactly.
   - **Published Checks:** Queries the Google Fact Check Tools API and maps publisher ratings to Luminate's labels.
   - **Web Research:** A model with a search tool drafts a short report. **Strict code rules apply:** sources must be actual returned URLs, definitive labels require two independent domains, and every sentence must be backed by a quoted passage (or it is dropped).
5. **Reconcile:** Claims are reviewed together. A claim can cite a sibling's sources to resolve contradictions, maintaining the same strict evidence rules.
6. **Origin Signals (Parallel):** Checks for Content Credentials (C2PA), runs an AI-image detector, and performs a reverse image search filtered to reputable publishers (Wikimedia, wire services, major newsrooms).
7. **Summarize:** The final headline verdict (Likely false, Partly false, Needs context, Checks out, Unverified) is calculated via code based on the underlying labels. It can never claim more than the compiled evidence supports.

The resulting card mirrors a critical reader's internal monologue: _Where did this come from? What is it claiming? How is it trying to persuade me?_

## Core design principles

- **Code enforces the evidence, not the prompt.** Hallucinated sources, single-source verdicts, and unsupported sentences are programmatically stripped out. A confident LLM cannot talk its way past the evidence rules.
- **Local by default where privacy matters.** OCR and image descriptions run locally.
- **Persuasion is a cue, not a verdict.** Manipulative phrasing (e.g., false urgency) is flagged for user awareness but never alters the factual label of a claim.
- **Fast enough for live reading.** The research stage uses a fast model with capped search limits. Heavy tasks are cached, and detectors have strict spending/timeout caps.

## Getting started

The fastest way to spin this up on Windows or Linux is via the [Quickstart guide](README-QUICKSTART.md) (one setup script, one model script, three terminals).

On Windows, `scripts\setup.cmd` installs both Python services and all Node projects;
`scripts\setup-model.cmd` configures the local vision model, and `scripts\start.cmd` starts the app.
To build the extension from the repository root, run `npm.cmd --prefix extension run build`
on Windows (`npm --prefix extension run build` on Linux), then load `extension/dist` as an
unpacked extension in Chrome. For backend configuration, stage mapping, and Postgres setup,
see [`src/README.md`](src/README.md).

**API Keys & Offline Mode:**
Without API keys, the backend automatically falls back to a clearly labeled offline mode using simple rules—perfect for testing the flow. Live fact-checking requires an Anthropic key. The AI detector, published fact-checks, and reverse image search can each be enabled with their respective keys.

## Repository layout

```text
src/factcheck/          # Backend: stages, prompts, services, store
frontend/               # React web app
frontend/image-context/ # Local OCR + vision service
extension/              # Chrome extension
reddit-bot/             # Devvit scaffold with offline runner
eval/                   # Regression cases and testing harness
tests/                  # Offline tests with a fake model backend
scripts/                # Setup scripts (PowerShell and bash)
ANALYSIS.md             # Known risks and architecture decisions
```

## Sources

[^1]: St. Aubin, Christopher, and Jacob Liedke. “Social Media and News Fact Sheet.” Pew Research Center, Pew Research Center, 25 Sept. 2025, www.pewresearch.org/journalism/fact-sheet/social-media-and-news-fact-sheet/.
