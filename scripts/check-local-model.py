"""Verify a real local image-model response, independently of the fake fact-check backend."""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from image_context.pipeline import analyze_image


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=root / "frontend/demo-preview.png")
    args = parser.parse_args()
    load_dotenv(root / "frontend/image-context/.env")
    model = os.getenv("VISION_MODEL", "qwen3-vl:4b-instruct")
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    if os.getenv("VISION_ENABLED", "true").lower() != "true":
        print("FAIL: VISION_ENABLED is false. Enable it in frontend/image-context/.env.")
        return 1
    try:
        response = httpx.get(f"{url}/api/tags", timeout=5, trust_env=False)
        response.raise_for_status()
        names = {item.get("name") for item in response.json().get("models", [])}
        if model not in names:
            print(f"FAIL: Model {model} is not downloaded. Run: ollama pull {model}")
            return 1
    except (httpx.HTTPError, ValueError, TypeError):
        print("FAIL: Ollama is unavailable. Install/open Ollama, then retry.")
        return 1
    try:
        print(f"Sending {args.image.name} to {model}. The first response can take a few minutes.", flush=True)
        result = analyze_image(args.image.read_bytes(), args.image.name, {}, include_vision=True)
    except (OSError, ValueError) as exc:
        print(f"FAIL: Could not analyze the image: {exc}")
        return 1
    if result.vision.get("status") != "ok":
        print("FAIL: The image model did not return a valid description.")
        for warning in result.warnings:
            print(warning)
        return 1
    observations = result.vision["observations"]
    if not observations.get("description", "").strip():
        print("FAIL: The model returned an empty description.")
        return 1
    print(f"PASS: {model} returned a real image description.")
    print(json.dumps(observations, indent=2, ensure_ascii=False))
    print(f"OCR status: {result.ocr['status']}")
    if result.ocr["status"] != "ok":
        print("Install/configure Tesseract to enable image text extraction too.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
