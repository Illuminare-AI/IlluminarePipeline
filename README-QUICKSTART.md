# Quick local setup (Windows)

## Setup once

Install Python 3.11+, Node.js, [Ollama](https://docs.ollama.com/windows), and
[Tesseract with English data](https://tesseract-ocr.github.io/tessdoc/Installation.html).

Open PowerShell in `C:\Github\IlluminarePipeline`:

```powershell
.\scripts\setup.ps1
.\scripts\setup-model.ps1
npm --prefix frontend ci
```

The model setup starts Ollama, downloads [qwen3-vl:4b-instruct](https://ollama.com/library/qwen3-vl:4b-instruct)
(about 3.3 GB), and configures both `.env` files. If Tesseract is installed somewhere other than
`C:\Program Files\Tesseract-OCR`, set `TESSERACT_CMD` in `frontend/image-context/.env` to its executable.

## Start the app: three commands

Keep Ollama running. Open **three PowerShell terminals**, each in `C:\Github\IlluminarePipeline`.

**Terminal 1 — image text and local descriptions**

```powershell
.\.venv\Scripts\python.exe -m uvicorn image_context.api:app --port 8001 --env-file frontend/image-context/.env
```

**Terminal 2 — backend**

```powershell
.\.venv\Scripts\python.exe -m uvicorn factcheck.api:app --port 8000 --env-file .env
```

**Terminal 3 — frontend**

```powershell
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

`PASS` means a real image description was returned. To test your own image, add its path to
that command. The description is local; fact-checks still use offline rules with
`LLM_BACKEND=fake`. Live fact-checking requires the Anthropic backend and its API key.

## Docker alternative

`docker compose up --build -d` starts the backend, OCR, and Ollama and downloads the model
on first launch. Then run only Terminal 3 above. Do not run Docker and native backend services
on the same ports. Docker keeps its own model download in a persistent volume.
