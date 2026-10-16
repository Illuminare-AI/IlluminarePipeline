# Quick local setup (Windows and Linux)

Each step shows the Windows (PowerShell) command first and the Linux (bash) command second.
The Linux commands also work on macOS and in WSL.

## Setup once

Install Python 3.11+, Node.js, Ollama ([Windows](https://docs.ollama.com/windows),
[Linux](https://ollama.com/download/linux)), and
[Tesseract with English data](https://tesseract-ocr.github.io/tessdoc/Installation.html).
On Debian/Ubuntu: `sudo apt install python3-venv tesseract-ocr`.

Open a terminal in the repository (`C:\Github\IlluminarePipeline` on Windows):
Stop any running app/dev servers before rerunning setup so Windows can replace installed packages.

**Windows**

```powershell
.\scripts\setup.cmd
.\scripts\setup-model.cmd
```

**Linux**

```bash
bash scripts/setup.sh
bash scripts/setup-model.sh
npm --prefix frontend ci
```

The Windows setup installs both Python services and all three Node projects (frontend, extension,
and Reddit bot), and creates the local `.env` files without replacing existing API keys.
The `.cmd` launchers run PowerShell with a process-only execution-policy override; no system policy
change is needed. You can also run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1`
directly. Use `-SkipNode` to install only Python. Node.js 24+ is recommended for all repository tests.

The model setup starts Ollama, downloads [qwen3-vl:4b-instruct](https://ollama.com/library/qwen3-vl:4b-instruct)
(about 3.3 GB), and configures both `.env` files. On Windows, if Tesseract is installed somewhere other than
`C:\Program Files\Tesseract-OCR`, set `TESSERACT_CMD` in `frontend/image-context/.env` to its executable.
On Linux, Tesseract is picked up from `PATH`; set `TESSERACT_CMD` only if it is installed elsewhere.

## Start the app

On Windows, start all three services from one terminal:

```powershell
.\scripts\start.cmd
```

Open **http://localhost:5173**. Press **Ctrl+C** in that terminal to stop the three services.
Ollama runs separately; keep it open for local image descriptions.

### Start services separately (Windows and Linux)

Keep Ollama running. Open **three terminals**, each in the repository root.

**Terminal 1 — image text and local descriptions**

```powershell
.\.venv\Scripts\python.exe -m uvicorn image_context.api:app --port 8001 --env-file frontend/image-context/.env
```

```bash
.venv/bin/python -m uvicorn image_context.api:app --port 8001 --env-file frontend/image-context/.env
```

**Terminal 2 — backend**

```powershell
.\.venv\Scripts\python.exe -m uvicorn factcheck.api:app --port 8000 --env-file .env
```

```bash
.venv/bin/python -m uvicorn factcheck.api:app --port 8000 --env-file .env
```

**Terminal 3 — frontend**

```powershell
npm.cmd --prefix frontend run dev
```

```bash
npm --prefix frontend run dev
```

Open the frontend address printed in Terminal 3, usually **http://localhost:5173**.
Upload an image and click **Check this screenshot**. Its actual bytes go to the local model;
the result includes **What's in the image?** with a description and any uncertainties.
The first image can take longer while the model loads. Restart services after changing `.env`.

## Check the model directly

```powershell
.\.venv\Scripts\python.exe scripts/check-local-model.py
```

```bash
.venv/bin/python scripts/check-local-model.py
```

`PASS` means a real image description was returned. To test your own image, add its path to
that command. The description is local; fact-checks still use offline rules with
`LLM_BACKEND=fake`. Live fact-checking requires the Anthropic backend and its API key.

## Docker alternative

`docker compose up --build -d` (same on Windows and Linux) starts the backend, OCR, and Ollama and downloads the model
on first launch. Then run only Terminal 3 above. Do not run Docker and native backend services
on the same ports. Docker keeps its own model download in a persistent volume.
