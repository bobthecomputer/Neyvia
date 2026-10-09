"""Provision ignored interpreter-local bytecode at the normal entry points."""
from __future__ import annotations

import compileall
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def ensure_bytecode(repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[2]).resolve()
    started = time.monotonic()
    package = repo / "src/grant_agent"
    # compileall checks existing cache headers, so changed source and a new
    # interpreter provision themselves without a committed machine-specific stamp.
    if not compileall.compile_dir(str(package), quiet=2):
        raise RuntimeError("Local Python bytecode provisioning failed")
    entry = repo / "scripts/fixcl_verify.py"
    if entry.exists() and not compileall.compile_file(str(entry), quiet=2):
        raise RuntimeError("Local CL entry bytecode provisioning failed")
    sources = list(package.rglob("*.py")) + ([entry] if entry.exists() else [])
    count = sum(Path(importlib.util.cache_from_source(str(path))).is_file() for path in sources)
    result = {"schema": "neyvia.bytecode-provision.v1", "ok": count == len(sources),
              "interpreter": sys.implementation.cache_tag, "sources": len(sources),
              "implicitImportWritesDisabled": sys.dont_write_bytecode,
              "cached": count, "ms": round((time.monotonic() - started) * 1000)}
    target = Path(os.environ.get("NEYVIA_PROVISIONING_ROOT", repo / ".agent_control/provisioning")).resolve()
    target.mkdir(parents=True, exist_ok=True)
    temporary = target / (f"bytecode-{os.getpid()}.part")
    temporary.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target / "bytecode.json")
    return result
