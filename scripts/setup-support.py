"""File-based setup helpers: compatible with PowerShell 5.1 native argument handling."""
import argparse
import importlib.util
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def update_env(path: Path, updates: dict[str, str]) -> None:
    if not path.exists():
        example = path.with_name('.env.example')
        shutil.copyfile(example, path)
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=', line)
        if match and match[1] in updates:
            key = match[1]
            lines[index] = f"{key}='{updates[key]}'"
            remaining.pop(key, None)
    lines.extend(f"{key}='{value}'" for key, value in remaining.items())
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['base', 'version', 'probe', 'verify', 'configure'])
    parser.add_argument('--model', default='qwen3-vl:4b-instruct')
    args = parser.parse_args()
    if args.action == 'base':
        print(sys._base_executable)
    elif args.action == 'version':
        if sys.version_info < (3, 11):  # noqa: UP036 - this also runs before installing the project
            raise SystemExit('Python 3.11 or newer required')
        print(f'{sys.version_info.major}.{sys.version_info.minor}')
    elif args.action == 'probe':
        for module in ('PIL.Image', 'pydantic_core', 'numpy', 'scipy'):
            if importlib.util.find_spec(module.split('.')[0]):
                __import__(module)
    elif args.action == 'verify':
        for module in ('PIL.Image', 'pydantic_core', 'scipy.fftpack', 'factcheck.api', 'image_context.api'):
            __import__(module)
        print('Backend, OCR and native imports verified')
    else:
        update_env(ROOT / '.env', {
            'IMAGE_CONTEXT_URL': 'http://127.0.0.1:8001',
            'IMAGE_VISION_ENABLED': 'true', 'IMAGE_CONTEXT_TIMEOUT': '600',
        })
        updates = {
            'OLLAMA_URL': 'http://127.0.0.1:11434', 'VISION_MODEL': args.model,
            'VISION_ENABLED': 'true', 'VISION_TIMEOUT': '540',
        }
        tesseract = shutil.which('tesseract')
        if not tesseract:
            candidate = Path('C:/Program Files/Tesseract-OCR/tesseract.exe')
            if candidate.is_file():
                tesseract = str(candidate)
        if tesseract:
            updates['TESSERACT_CMD'] = Path(tesseract).as_posix()
        else:
            print('Warning: install Tesseract or set TESSERACT_CMD in frontend/image-context/.env.')
        update_env(ROOT / 'frontend/image-context/.env', updates)
        frontend_env = ROOT / 'frontend/.env'
        if not frontend_env.exists():
            shutil.copyfile(frontend_env.with_name('.env.example'), frontend_env)
        print('Local environment configured; existing API keys preserved.')


if __name__ == '__main__':
    main()
