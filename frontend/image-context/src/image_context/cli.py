import argparse
import json
from pathlib import Path
from .pipeline import analyze_image


def main():
    parser = argparse.ArgumentParser(description="Extract local image context as JSON")
    parser.add_argument("image", type=Path)
    parser.add_argument("--context", default="")
    parser.add_argument("--no-vision", action="store_true")
    args = parser.parse_args()
    result = analyze_image(args.image.read_bytes(), args.image.name, {"caption": args.context}, not args.no_vision)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
