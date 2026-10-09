from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs


SHARED_LIBRARY_RE = re.compile(r"(lib[A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*)")

COMMON_BROWSER_DEPENDENCY_PACKAGES = [
    "libatk1.0-0",
    "libatk-bridge2.0-0",
    "libcups2",
    "libdrm2",
    "libgtk-3-0",
    "libnss3",
    "libxss1",
    "libasound2",
    "libxcomposite1",
    "libxdamage1",
    "libxrandr2",
    "libgbm1",
    "libxkbcommon0",
]

MISSING_LIBRARY_PACKAGE_MAP = {
    "libatk-1.0.so.0": ["libatk1.0-0"],
    "libatk-bridge-2.0.so.0": ["libatk-bridge2.0-0"],
    "libatspi.so.0": ["libatk-bridge2.0-0"],
    "libcups.so.2": ["libcups2"],
    "libdrm.so.2": ["libdrm2"],
    "libgtk-3.so.0": ["libgtk-3-0"],
    "libnss3.so": ["libnss3"],
    "libXss.so.1": ["libxss1"],
    "libasound.so.2": ["libasound2"],
    "libxcomposite.so.1": ["libxcomposite1"],
    "libxdamage.so.1": ["libxdamage1"],
    "libxrandr.so.2": ["libxrandr2"],
    "libgbm.so.1": ["libgbm1"],
    "libxkbcommon.so.0": ["libxkbcommon0"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chrome_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    env_browser_path = str(os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or "").strip()
    if env_browser_path:
        candidates.append(Path(env_browser_path))
    for executable in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))
    browser_roots = [
        Path(str(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "")),
        Path.home() / ".cache" / "ms-playwright",
        root / ".agent_control" / "runtime" / "home" / ".cache" / "ms-playwright",
        root.parent / "runtime" / "home" / ".cache" / "ms-playwright",
        root.parent.parent / "runtime" / "home" / ".cache" / "ms-playwright",
        root.parent.parent / ".cache" / "ms-playwright",
    ]
    for browser_root in browser_roots:
        if not str(browser_root) or not browser_root.exists():
            continue
        # Keep this bounded. The watchdog calls this preflight on every pass, and
        # recursive globbing through runtime/cache folders can stall the whole
        # mission supervisor before it writes a completed receipt.
        candidates.extend(browser_root.glob("*/chrome-linux64/chrome"))
        candidates.extend(browser_root.glob("*/chrome-linux/chrome"))
        candidates.extend(browser_root.glob("*/chrome-win/chrome.exe"))
        candidates.extend(browser_root.glob("chromium-*/chrome-linux/chrome"))
        candidates.extend(browser_root.glob("chromium-*/chrome-win/chrome.exe"))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _browser_library_paths(root: Path) -> list[Path]:
    bases = [
        root / ".agent_control" / "runtime" / "browser-libs-bullseye" / "root",
        root.parent / "runtime" / "browser-libs-bullseye" / "root",
        root.parent.parent / "runtime" / "browser-libs-bullseye" / "root",
    ]
    paths: list[Path] = []
    for base in bases:
        for relative in (
            Path("usr/lib/x86_64-linux-gnu"),
            Path("usr/lib"),
            Path("lib/x86_64-linux-gnu"),
            Path("lib"),
        ):
            candidate = base / relative
            if candidate.exists():
                paths.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _dedupe(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _packages_for_missing_libraries(missing_libraries: list[str]) -> list[str]:
    packages: list[str] = []
    for library in missing_libraries:
        packages.extend(MISSING_LIBRARY_PACKAGE_MAP.get(library, []))
    return _dedupe([*packages, *COMMON_BROWSER_DEPENDENCY_PACKAGES])


def _package_manager() -> dict[str, Any]:
    apt = shutil.which("apt-get")
    if not apt:
        return {
            "id": "",
            "path": "",
            "supportsInstall": False,
            "requiresRoot": True,
            "rootAvailable": False,
            "reason": "No supported non-interactive package manager was found.",
        }
    running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0
    sudo = shutil.which("sudo")
    root_prefix = [] if running_as_root else [sudo, "-n"] if sudo else []
    return {
        "id": "apt-get",
        "path": apt,
        "supportsInstall": True,
        "requiresRoot": not running_as_root,
        "rootAvailable": running_as_root or bool(sudo),
        "rootPrefix": root_prefix,
        "reason": "",
    }


def _repair_plan(status: str, missing_libraries: list[str]) -> dict[str, Any]:
    package_manager = _package_manager()
    packages = _packages_for_missing_libraries(missing_libraries)
    browser_install_command = [sys.executable, "-m", "playwright", "install", "chromium"]
    commands: list[dict[str, Any]] = []
    if status == "missing_browser":
        commands.append(
            {
                "id": "install_playwright_chromium",
                "label": "Install Playwright Chromium for the runtime user",
                "commandParts": browser_install_command,
                "command": " ".join(browser_install_command),
                "requiresRoot": False,
            }
        )
    if status == "dependency_missing" and packages:
        if package_manager.get("supportsInstall") and package_manager.get("rootAvailable"):
            root_prefix = list(package_manager.get("rootPrefix") or [])
            commands.extend(
                [
                    {
                        "id": "apt_update",
                        "label": "Refresh apt package metadata",
                        "commandParts": [*root_prefix, "apt-get", "update"],
                        "command": " ".join([*root_prefix, "apt-get", "update"]),
                        "requiresRoot": bool(package_manager.get("requiresRoot")),
                    },
                    {
                        "id": "apt_install_browser_dependencies",
                        "label": "Install Chromium shared-library dependencies",
                        "commandParts": [*root_prefix, "apt-get", "install", "-y", *packages],
                        "command": " ".join([*root_prefix, "apt-get", "install", "-y", *packages]),
                        "requiresRoot": bool(package_manager.get("requiresRoot")),
                    },
                ]
            )
    if status == "passed":
        plan_status = "not_needed"
        next_action = "Browser proof dependencies are already available."
    elif commands:
        plan_status = "ready_to_repair"
        next_action = "Run browser-deps-preflight --repair to install missing browser proof dependencies."
    elif status == "dependency_missing":
        plan_status = "blocked"
        next_action = (
            "Install Chromium shared-library dependencies with a supported package manager or provide "
            "a runtime browser library bundle."
        )
    elif status == "missing_browser":
        plan_status = "ready_to_repair"
        next_action = "Run browser-deps-preflight --repair to install Playwright Chromium for the runtime user."
    else:
        plan_status = "manual_review"
        next_action = "Inspect the preflight error before requiring browser proof."
    return {
        "schema": "fluxio.browser_dependency_repair_plan.v1",
        "status": plan_status,
        "missingLibraries": missing_libraries,
        "packages": packages,
        "packageManager": package_manager,
        "commands": commands,
        "nextAction": next_action,
    }


def _install_hint(missing_libraries: list[str]) -> str:
    plan = _repair_plan("dependency_missing" if missing_libraries else "failed", missing_libraries)
    install_commands = [item.get("command", "") for item in plan.get("commands", []) if item.get("command")]
    if install_commands:
        return " && ".join(install_commands)
    if missing_libraries:
        return (
            "Install the missing Chrome shared libraries on the NAS host or run browser proof "
            "inside a Playwright-compatible container; missing: "
            + ", ".join(missing_libraries)
        )
    return "Install Playwright browser dependencies on the runtime host before requiring screenshot proof."


def _build_browser_dependency_preflight(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    checked_at = _utc_now()
    candidates = _chrome_candidates(root)
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return {
            "schema": "fluxio.browser_dependency_preflight.v1",
            "checkedAt": checked_at,
            "root": str(root),
            "status": "missing_browser",
            "browserProofAvailable": False,
            "chromeExecutable": "",
            "missingLibraries": [],
            "error": "No Chromium/Chrome executable was found for Playwright proof.",
            "installHint": "Run Playwright browser install for the runtime user, then rerun this preflight.",
            "repairPlan": _repair_plan("missing_browser", []),
        }

    chrome = existing[0]
    library_paths = _browser_library_paths(root)
    env = os.environ.copy()
    ld_library_path = ":".join(str(path) for path in library_paths)
    if ld_library_path:
        env["LD_LIBRARY_PATH"] = (
            ld_library_path
            + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        )
    try:
        completed = subprocess.run(
            [str(chrome), "--version"],
            cwd=str(root),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "schema": "fluxio.browser_dependency_preflight.v1",
            "checkedAt": checked_at,
            "root": str(root),
            "status": "failed",
            "browserProofAvailable": False,
            "chromeExecutable": str(chrome),
            "ldLibraryPath": ld_library_path,
            "missingLibraries": [],
            "error": str(exc),
            "installHint": _install_hint([]),
            "repairPlan": _repair_plan("failed", []),
        }

    output = f"{completed.stdout}\n{completed.stderr}".strip()
    missing_libraries = sorted(set(SHARED_LIBRARY_RE.findall(output)))
    if completed.returncode != 0:
        status = "dependency_missing" if missing_libraries else "failed"
        return {
            "schema": "fluxio.browser_dependency_preflight.v1",
            "checkedAt": checked_at,
            "root": str(root),
            "status": status,
            "browserProofAvailable": False,
            "chromeExecutable": str(chrome),
            "ldLibraryPath": ld_library_path,
            "missingLibraries": missing_libraries,
            "error": output[:2000],
            "installHint": _install_hint(missing_libraries),
            "repairPlan": _repair_plan(status, missing_libraries),
        }

    return {
        "schema": "fluxio.browser_dependency_preflight.v1",
        "checkedAt": checked_at,
        "root": str(root),
        "status": "passed",
        "browserProofAvailable": True,
        "chromeExecutable": str(chrome),
        "ldLibraryPath": ld_library_path,
        "missingLibraries": [],
        "version": output,
        "installHint": "",
        "repairPlan": _repair_plan("passed", []),
    }


def build_browser_dependency_preflight(root: Path) -> dict[str, Any]:
    result = _build_browser_dependency_preflight(root)
    from .proofs_a_control import require
    require(result["browserProofAvailable"] is (result["status"] == "passed")
            and (result["status"] != "dependency_missing" or bool(result["missingLibraries"]))
            and (result["status"] != "dependency_missing" or all(
                package in result["repairPlan"]["packages"] for library in result["missingLibraries"]
                for package in MISSING_LIBRARY_PACKAGE_MAP.get(library, []))),
            "control.browser-preflight", "browser availability or dependency package plan contradicts observed status")
    return result


def write_browser_dependency_preflight(root: Path) -> dict[str, Any]:
    payload = build_browser_dependency_preflight(root)
    path = Path(root).resolve() / ".agent_control" / "browser_dependency_preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["receiptPath"] = str(path)
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2))
    return payload


def _run_repair_command(command: list[str], *, root: Path, timeout_seconds: int) -> dict[str, Any]:
    started_at = _utc_now()
    try:
        completed = subprocess.run(
            command,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(30, int(timeout_seconds or 900)),
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": " ".join(command),
            "startedAt": started_at,
            "endedAt": _utc_now(),
            "status": "failed",
            "exitCode": None,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
        }
    return {
        "command": " ".join(command),
        "startedAt": started_at,
        "endedAt": _utc_now(),
        "status": "completed" if completed.returncode == 0 else "failed",
        "exitCode": completed.returncode,
        "stdout": str(completed.stdout or "")[-4000:],
        "stderr": str(completed.stderr or "")[-4000:],
    }


_REPAIR_LOCKS = tuple(threading.RLock() for _ in range(64))


def repair_browser_dependencies(
    root: Path,
    *,
    dry_run: bool = False,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    from .harness_jobs import _exclusive_job_lock
    root = Path(root).resolve()
    path = root / ".agent_control" / "browser_dependency_repair.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _REPAIR_LOCKS[hash(str(path).casefold()) % len(_REPAIR_LOCKS)]
    with lock, _exclusive_job_lock(path, timeout_seconds=max(30, timeout_seconds)):
        return _repair_browser_dependencies_locked(root, dry_run=dry_run, timeout_seconds=timeout_seconds)


def _repair_browser_dependencies_locked(
    root: Path,
    *,
    dry_run: bool = False,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    root = Path(root).resolve()
    before = build_browser_dependency_preflight(root)
    actions: list[dict[str, Any]] = []
    for command in before.get("repairPlan", {}).get("commands", []):
        command_parts = [str(item) for item in list(command.get("commandParts") or []) if str(item or "").strip()]
        if not command_parts:
            continue
        action = {
            "id": command.get("id", "repair_command"),
            "label": command.get("label", "Browser dependency repair command"),
            "command": " ".join(command_parts),
            "dryRun": bool(dry_run),
        }
        if dry_run:
            actions.append({**action, "status": "planned"})
            continue
        result = _run_repair_command(command_parts, root=root, timeout_seconds=timeout_seconds)
        actions.append({**action, **result})
        if result.get("status") != "completed":
            break
    after = before if dry_run else build_browser_dependency_preflight(root)
    payload = {
        "schema": "fluxio.browser_dependency_repair.v1",
        "checkedAt": _utc_now(),
        "root": str(root),
        "dryRun": bool(dry_run),
        "status": (
            "passed"
            if after.get("status") == "passed"
            else "planned"
            if dry_run and actions
            else "blocked"
            if not actions and before.get("status") != "passed"
            else "failed"
            if any(item.get("status") == "failed" for item in actions)
            else after.get("status", "unknown")
        ),
        "before": before,
        "actions": actions,
        "after": after,
        "nextAction": (
            "Browser proof dependencies are ready."
            if after.get("status") == "passed"
            else after.get("repairPlan", {}).get("nextAction")
            or before.get("repairPlan", {}).get("nextAction")
            or "Inspect the browser dependency repair receipt."
        ),
    }
    path = root / ".agent_control" / "browser_dependency_repair.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["receiptPath"] = str(path)
    from .durability import atomic_write_text
    atomic_write_text(path, json.dumps(payload, indent=2))
    write_browser_dependency_preflight(root)
    from .proofs_a_control import require
    require(json.loads(path.read_text(encoding="utf-8")) == payload
            and (not dry_run or all(action["status"] == "planned" and action["dryRun"] for action in actions))
            and (not dry_run or payload["before"] == payload["after"]),
            "control.browser-repair", "repair receipt differs from persisted plan or dry run claims execution")
    return payload
