#!/usr/bin/env python3
"""Plan NAS storage cleanup actions."""
from __future__ import annotations
import argparse
import json

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    print(json.dumps({"ok": True, "root": args.root}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
