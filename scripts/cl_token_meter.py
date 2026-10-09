"""Measure input text with exact o200k and a labelled Claude approximation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grant_agent.cl.tokens import measure_tokens


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="UTF-8 files; otherwise read stdin")
    parser.add_argument("--text", help="Measure this literal text instead")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.files and args.text is not None:
        parser.error("Use files or --text, not both")
    inputs = {str(path): path.read_text(encoding="utf-8-sig") for path in args.files}
    if not inputs:
        inputs = {"text" if args.text is not None else "stdin": args.text if args.text is not None else sys.stdin.read()}
    result = {name: measure_tokens(value) for name, value in inputs.items()}
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
