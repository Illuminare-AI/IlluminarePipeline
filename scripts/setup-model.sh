#!/usr/bin/env bash
# Linux/macOS counterpart of setup-model.ps1: starts Ollama, downloads the vision model, configures both .env files.
# Usage: bash scripts/setup-model.sh [model]
set -euo pipefail

model="${1:-qwen3-vl:4b-instruct}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_python="$root/.venv/bin/python"

if ! command -v ollama >/dev/null 2>&1; then
    echo 'Install Ollama (https://ollama.com/download/linux), then run this command again.' >&2
    exit 1
fi
if ! [ -x "$venv_python" ]; then
    echo 'Run scripts/setup.sh first.' >&2
    exit 1
fi
mkdir -p "$root/.tmp"

ollama_up() { curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }

if ! ollama_up; then
    nohup ollama serve >"$root/.tmp/ollama-server.log" 2>"$root/.tmp/ollama-server-error.log" &
    for _ in $(seq 1 66); do
        if ollama_up; then break; fi
        sleep 0.3
    done
    if ! ollama_up; then
        echo 'Ollama did not start. Check .tmp/ollama-server-error.log.' >&2
        exit 1
    fi
fi

ollama pull "$model"

cd "$root"
"$venv_python" - "$model" <<'EOF'
import re
import shutil
import sys
from pathlib import Path

model = sys.argv[1]
for name in ('.env', 'frontend/image-context/.env'):
    path = Path(name)
    if not path.exists():
        example = path.with_name('.env.example')
        path.write_text(example.read_text() if example.exists() else '', encoding='utf-8')


def update_env(name, updates):
    path = Path(name)
    lines = path.read_text(encoding='utf-8').splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=', line)
        if match and match[1] in updates:
            key = match[1]
            lines[index] = f"{key}='{updates[key]}'"
            remaining.pop(key, None)
    lines.extend(f"{key}='{value}'" for key, value in remaining.items())
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


update_env('.env', {'IMAGE_CONTEXT_URL': 'http://127.0.0.1:8001', 'IMAGE_VISION_ENABLED': 'true', 'IMAGE_CONTEXT_TIMEOUT': '600'})
updates = {'OLLAMA_URL': 'http://127.0.0.1:11434', 'VISION_MODEL': model, 'VISION_ENABLED': 'true', 'VISION_TIMEOUT': '540'}
tesseract = shutil.which('tesseract')
if tesseract:
    updates['TESSERACT_CMD'] = tesseract
else:
    print('Warning: tesseract is not on PATH. Install it (e.g. sudo apt install tesseract-ocr) or set TESSERACT_CMD in frontend/image-context/.env.')
update_env('frontend/image-context/.env', updates)
print('Local image model configured. Start the three services from README-QUICKSTART.md.')
EOF
