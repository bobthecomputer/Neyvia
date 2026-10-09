"""Resolve the installed Hermes runtime and read its native plugin inventory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

_CACHE: dict = {}
_LOCK = threading.Lock()


def hermes_python(command: str, env: dict) -> Path:
    explicit = env.get("NEYVIA_HERMES_PYTHON")
    executable = Path(command).resolve()
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([executable.with_name("python.exe"), executable.with_name("python")])
    for parent in executable.parents:
        candidates.append(parent / "hermes-agent" / "venv" / "Scripts" / "python.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("Hermes system delivery requires its Python runtime. Set NEYVIA_HERMES_PYTHON to the Hermes interpreter; instructions will not be downgraded to user text.")


def plugin_inventory(*, environment: dict | None = None) -> dict:
    from .proofs_e_release import check_hermes_inventory
    snapshot = os.environ.copy() if environment is None else dict(environment)
    command = shutil.which("hermes", path=snapshot.get("PATH", ""))
    if not command:
        return check_hermes_inventory({"available": False, "plugins": [], "error": "Hermes CLI is not installed"})
    key = (command, snapshot.get("HERMES_HOME", ""))
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return check_hermes_inventory(cached[1])
        try:
            result = subprocess.run([command, "plugins", "list", "--json"], capture_output=True,
                                    text=True, encoding="utf-8", timeout=25,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=snapshot)
            if result.returncode:
                raise RuntimeError("Hermes plugin listing failed")
            rows = json.loads(result.stdout.lstrip("\ufeff"))
            if not isinstance(rows, list):
                raise ValueError("Hermes returned an invalid plugin inventory")
            # Whitelist public metadata, excluding paths, configuration and credentials.
            plugins = [{key: str(row.get(key) or "") for key in
                        ("name", "description", "version", "status", "source")}
                       for row in rows if isinstance(row, dict)]
            value = {"available": True, "plugins": plugins, "error": ""}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            value = {"available": False, "plugins": [], "error": type(exc).__name__}
        _CACHE[key] = (time.monotonic(), value)
        return check_hermes_inventory(value)
