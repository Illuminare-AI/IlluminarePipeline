#!/usr/bin/env bash
# Linux/macOS counterpart of setup.ps1: installs both Python projects into the root .venv.
# Usage: bash scripts/setup.sh [/path/to/python3]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$root/.venv"
venv_python="$venv/bin/python"
tmp="$root/.tmp"

python_path="${1:-}"
if [ -z "$python_path" ]; then
    if [ -x "$venv_python" ]; then
        python_path="$("$venv_python" -c 'import sys; print(sys._base_executable)')"
    else
        python_path="$(command -v python3 || command -v python || true)"
    fi
fi
if [ -z "$python_path" ] || ! [ -x "$python_path" ]; then
    echo "Provide a working base Python executable: bash scripts/setup.sh /path/to/python3" >&2
    exit 1
fi
"$python_path" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer required"'
"$python_path" -c 'import ensurepip' 2>/dev/null || {
    echo "This Python cannot create virtual environments. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    exit 1
}
base_version="$("$python_path" -c 'import sys; print("%s.%s" % sys.version_info[:2])')"

mkdir -p "$tmp"
export TMPDIR="$tmp"
cd "$root"

if [ -d "$venv" ]; then
    valid=0
    if [ -x "$venv_python" ]; then
        env_version="$("$venv_python" -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>/dev/null || true)"
        if [ "$env_version" = "$base_version" ]; then
            # Missing packages are installed below; broken native imports require a clean environment.
            if "$venv_python" -c 'import importlib.util; modules = ["PIL.Image", "pydantic_core", "numpy", "scipy"]; [__import__(m) for m in modules if importlib.util.find_spec(m.split(".")[0])]' 2>/dev/null; then
                valid=1
            fi
        fi
    fi
    if [ "$valid" -ne 1 ]; then
        backup="$tmp/venv-before-repair-$(date +%Y%m%d%H%M%S)-$$"
        mv "$venv" "$backup"
        echo "Saved the incompatible environment in $backup"
    fi
fi

if ! [ -x "$venv_python" ]; then
    "$python_path" -m venv "$venv"
fi
"$venv_python" -m pip install --cache-dir .tmp/pip-cache --upgrade pip
"$venv_python" -m pip install --cache-dir .tmp/pip-cache -e '.[dev]' -e './frontend/image-context[test]'
"$venv_python" -m pip check
"$venv_python" -c 'from PIL import Image; import pydantic_core, scipy, factcheck.api, image_context.api; print("Backend, OCR and native imports verified")'
echo 'Setup complete. Both Python services are installed in the root .venv.'
