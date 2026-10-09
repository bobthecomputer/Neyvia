"""Keep Neyvia's managed Python environment in step with the bundled requirements.

The desktop shell creates ``runtime/venv`` once and installs the pinned, hash-checked
``backend-requirements.txt`` into it. Before this module an app update that changed the
requirements left the old environment in place. Now the SHA-256 of the requirements file
(line endings normalised) is recorded in the environment after a good install, and any
mismatch triggers one ``pip install --require-hashes`` run. ``src-tauri/src/runtime_env.rs``
uses the same marker file and hash, so either side can notice a change the other made.

    python -m grant_agent.venv_sync status --venv <dir> --requirements <file>
    python -m grant_agent.venv_sync sync   --venv <dir> --requirements <file> [--create-with <python>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .component_install import app_version, now, write_receipt
from .durability import atomic_write_json
from .subprocess_utils import hidden_windows_subprocess_kwargs

MARKER = ".neyvia-requirements.json"
MARKER_SCHEMA = "neyvia.venv_requirements.v1"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash(path: Path) -> str:
    text = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()


def pinned(path: Path) -> dict[str, str]:
    """name -> version for every ``name==version`` line (names normalised like pip)."""
    result: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = _PIN.match(line.strip())
        if match:
            result[re.sub(r"[-_.]+", "-", match[1]).lower()] = match[2]
    return result


def read_marker(venv: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((venv / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == MARKER_SCHEMA else None


def status(venv: Path, requirements: Path) -> dict[str, Any]:
    venv = Path(venv)
    wanted = requirements_hash(requirements)
    marker = read_marker(venv)
    if not venv_python(venv).is_file():
        state = "missing"
    elif marker is None:
        state = "unrecorded"  # built by an older Neyvia: one sync records it
    elif marker.get("sha256") == wanted:
        state = "current"
    else:
        state = "stale"
    return {"state": state, "bundledHash": wanted, "installedHash": (marker or {}).get("sha256"),
            "installedAt": (marker or {}).get("installedAt"), "venv": str(venv)}


def _run(command: list[str], runner: Callable[..., Any], timeout: int) -> Any:
    return runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                  timeout=timeout, check=False, **hidden_windows_subprocess_kwargs())


def installed_versions(python: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, str]:
    done = _run([str(python), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"], runner, 120)
    if done.returncode != 0:
        raise RuntimeError("pip list failed: " + str(done.stderr or done.stdout).strip()[:300])
    return {re.sub(r"[-_.]+", "-", row["name"]).lower(): row["version"] for row in json.loads(done.stdout)}


def sync(venv: Path, requirements: Path, *, create_with: str | None = None, pip_args: tuple[str, ...] = (),
         runtime_root: str | Path | None = None, force: bool = False,
         runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    """Install the bundled requirements when they changed. Returns a receipt (``ok`` tells success)."""
    venv, requirements = Path(venv), Path(requirements)
    before = status(venv, requirements)
    base = {"component": "python-venv", "venv": str(venv), "requirements": str(requirements),
            "bundledHash": before["bundledHash"], "previousHash": before["installedHash"]}
    if before["state"] == "current" and not force:
        return write_receipt(runtime_root, {**base, "ok": True, "status": "already_current", "action": "sync"})
    if before["state"] == "missing":
        if not create_with:
            return write_receipt(runtime_root, {**base, "ok": False, "status": "environment_missing", "action": "sync",
                                                "detail": "No environment to update; the desktop shell creates it first."})
        venv.parent.mkdir(parents=True, exist_ok=True)
        made = _run([create_with, "-m", "venv", str(venv)], runner, 300)
        if made.returncode != 0 or not venv_python(venv).is_file():
            return write_receipt(runtime_root, {**base, "ok": False, "status": "venv_failed", "action": "sync",
                                                "detail": str(made.stderr or made.stdout).strip()[:500]})
    python = venv_python(venv)
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes",
               "--only-binary=:all:", *pip_args, "-r", str(requirements)]
    done = _run(command, runner, 1800)
    if done.returncode != 0:
        # The marker keeps the old hash, so the next start retries. Nothing half-recorded.
        return write_receipt(runtime_root, {**base, "ok": False, "status": "install_failed", "action": "sync",
                                            "detail": str(done.stderr or done.stdout).strip()[-800:]})
    have = installed_versions(python, runner)
    wrong = {name: {"wanted": version, "have": have.get(name)}
             for name, version in pinned(requirements).items() if have.get(name) != version}
    if wrong:
        return write_receipt(runtime_root, {**base, "ok": False, "status": "verify_failed", "action": "sync",
                                            "detail": "Installed versions differ from the pins.", "mismatches": wrong})
    atomic_write_json(venv / MARKER, {"schema": MARKER_SCHEMA, "sha256": before["bundledHash"], "installedAt": now(),
                                      "appVersion": app_version(), "pins": len(pinned(requirements))})
    return write_receipt(runtime_root, {**base, "ok": True, "action": "sync",
                                        "status": "installed" if before["state"] != "stale" else "updated",
                                        "pins": len(pinned(requirements))})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Neyvia managed environment sync")
    parser.add_argument("action", choices=["status", "sync"])
    parser.add_argument("--venv", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--create-with")
    parser.add_argument("--runtime-root")
    args = parser.parse_args(argv)
    if args.action == "status":
        result = status(Path(args.venv), Path(args.requirements))
    else:
        result = sync(Path(args.venv), Path(args.requirements), create_with=args.create_with, runtime_root=args.runtime_root)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
