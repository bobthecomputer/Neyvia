"""Resolve a prepared dependency environment without mutating a sealed release."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path


def resolve(base: Path, release: Path) -> Path:
    digest = hashlib.sha256((release / "uv.lock").read_bytes()).hexdigest()
    environment = base / "runtime" / "neyvia-environments" / digest
    receipt = environment / ".neyvia-environment.json"
    try:
        ready = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("This release's locked dependency environment has not been prepared") from error
    interpreter = environment / "bin" / "python"
    if ready.get("status") != "ready" or ready.get("lockSha256") != digest or not interpreter.is_file():
        raise RuntimeError("Release dependency environment identity or readiness does not match")
    return interpreter


if __name__ == "__main__":
    print(resolve(Path(sys.argv[1]), Path(sys.argv[2])))
