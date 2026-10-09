"""\"Add Neyvia to my Claude Code\": install, update and remove the Neyvia plugin for the person's own Claude Code.

The plugin folder is copied once to a stable per-user marketplace folder
(``<runtime>/components/claude-mod/marketplace``), then registered with Claude Code's own CLI:

    claude plugin marketplace add <that folder>
    claude plugin install neyvia@neyvia

On an app update the marketplace folder is refreshed (staged, hashed, swapped) and
``claude plugin marketplace update`` + ``claude plugin update`` pull it into Claude Code; a
running Claude Code picks it up with ``/reload-plugins`` or on its next start. Claude Code's own
config directory (``CLAUDE_CONFIG_DIR``, default ``~/.claude``) is only ever written by that CLI.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .component_install import (REPO, app_version, components_root, copy_tree, now, read_manifest, recover_dir,
                                swap_dir, tree_files, tree_hash, unique_staging, verify_tree, write_manifest,
                                write_receipt)
from .subprocess_utils import hidden_windows_subprocess_kwargs

PLUGIN_SOURCE = REPO / "plugins" / "neyvia"
MARKETPLACE_SOURCE = REPO / ".claude-plugin" / "marketplace.json"
NAME = "neyvia"
PLUGIN_ID = "neyvia@neyvia"
# Development-only files that Claude Code never needs at run time.
IGNORE = frozenset({"types", "tsconfig.json", "tsconfig.tsbuildinfo"})


def claude_bin() -> str | None:
    return os.environ.get("NEYVIA_CLAUDE_BIN") or shutil.which("claude")


def folder(runtime_root: str | Path | None = None) -> Path:
    return components_root(runtime_root) / "claude-mod"


def marketplace_dir(runtime_root: str | Path | None = None) -> Path:
    return folder(runtime_root) / "marketplace"


def _cli(args: list[str], runner: Callable[..., Any], timeout: int = 120) -> tuple[int, dict | None, str]:
    binary = claude_bin()
    done = runner([binary, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                  timeout=timeout, check=False, stdin=subprocess.DEVNULL, **hidden_windows_subprocess_kwargs())
    text = str(done.stdout or "").strip()
    payload = None
    candidates = [text] + [line for line in reversed(text.splitlines()) if line.lstrip()[:1] in ("{", "[")]
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, (dict, list)):
                break
        except ValueError:
            continue
        payload = None
    return done.returncode, payload, (text + "\n" + str(done.stderr or "")).strip()[-600:]


def _source_files(plugin: Path | None = None) -> list[tuple[str, str]]:
    plugin = Path(plugin or PLUGIN_SOURCE)
    return tree_files(plugin, ignore=IGNORE)


def plugin_version(plugin: Path) -> str:
    try:
        return str(json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def bundled(plugin: Path | None = None) -> dict[str, Any]:
    plugin = Path(plugin or PLUGIN_SOURCE)
    rows = _source_files(plugin)
    market = MARKETPLACE_SOURCE.read_bytes() if MARKETPLACE_SOURCE.is_file() else b""
    import hashlib
    digest = tree_hash(rows + [("marketplace.json", hashlib.sha256(market).hexdigest())])
    return {"version": plugin_version(plugin), "treeSha256": digest, "files": len(rows)}


_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def installed_plugin(runner: Callable[..., Any] = subprocess.run, *, fresh: bool = False) -> dict[str, Any] | None:
    """Claude Code's own record of the plugin, or None when absent or the CLI is missing.

    Reads are cached for 20 s (a screen refresh must not start Claude Code's CLI every time);
    install and remove always ask again."""
    if not claude_bin():
        return None
    if not fresh and time.monotonic() - _CACHE["at"] < 20 and runner is subprocess.run:
        return _CACHE["value"]
    code, payload, _ = _cli(["plugin", "list", "--json"], runner)
    value = None
    if code == 0 and isinstance(payload, list):
        value = next((row for row in payload if isinstance(row, dict) and row.get("id") == PLUGIN_ID), None)
    if runner is subprocess.run and code == 0:
        _CACHE.update(at=time.monotonic(), value=value)
    return value


def status(runtime_root: str | Path | None = None, runner: Callable[..., Any] = subprocess.run,
           plugin: Path | None = None) -> dict[str, Any]:
    want = bundled(plugin)
    mark = read_manifest(folder(runtime_root) / "manifest.json")
    result = {"component": "claude-mod", "claudeFound": bool(claude_bin()), "bundledVersion": want["version"],
              "bundledHash": want["treeSha256"][:12], "appVersion": app_version(),
              "marketplaceDir": str(marketplace_dir(runtime_root))}
    if not claude_bin():
        return {**result, "state": "unavailable", "detail": "Claude Code is not installed on this PC."}
    claude = installed_plugin(runner)
    if claude is None or not mark:
        return {**result, "state": "not-installed", "installedVersion": None}
    problems = verify_tree(marketplace_dir(runtime_root), mark.get("files") or {})
    have = str(claude.get("version") or "")
    staged_current = mark.get("treeSha256") == want["treeSha256"]
    in_claude_current = have == str(mark.get("pluginVersion") or "")
    if problems:
        state = "broken"
    elif not staged_current or not in_claude_current:
        state = "update-available"
    else:
        state = "current"
    return {**result, "state": state, "installedVersion": have, "stagedVersion": mark.get("pluginVersion"),
            "enabled": claude.get("enabled"), "scope": claude.get("scope"), "problems": problems[:5],
            "installedAt": mark.get("installedAt")}


def _stage(runtime_root: str | Path | None, plugin: Path | None) -> dict[str, Any]:
    plugin = Path(plugin or PLUGIN_SOURCE)
    rows = _source_files(plugin)
    work = unique_staging(folder(runtime_root), "stage")
    try:
        copy_tree(plugin, work / "plugins" / NAME, rows)
        (work / ".claude-plugin").mkdir()
        shutil.copyfile(MARKETPLACE_SOURCE, work / ".claude-plugin" / "marketplace.json")
        staged = tree_files(work)
        live = marketplace_dir(runtime_root)
        swap_dir(work, live, folder(runtime_root) / "marketplace.previous")
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return {"files": dict(staged), "pluginVersion": plugin_version(plugin)}


def install(runtime_root: str | Path | None = None, runner: Callable[..., Any] = subprocess.run,
            plugin: Path | None = None) -> dict[str, Any]:
    """Install, or update when already installed. Idempotent."""
    if not claude_bin():
        return write_receipt(runtime_root, {"component": "claude-mod", "action": "install", "ok": False,
                                            "status": "claude_missing", "detail": "Claude Code is not installed on this PC."})
    recover_dir(marketplace_dir(runtime_root), folder(runtime_root) / "marketplace.previous")
    old_mark = read_manifest(folder(runtime_root) / "manifest.json") or {}
    before = installed_plugin(runner, fresh=True)
    want = bundled(plugin)
    steps: list[dict[str, Any]] = []
    try:
        staged = _stage(runtime_root, plugin)
    except Exception as exc:  # noqa: BLE001
        return write_receipt(runtime_root, {"component": "claude-mod", "action": "install", "ok": False,
                                            "status": "stage_failed", "detail": str(exc)[:400]})
    live = str(marketplace_dir(runtime_root))

    def step(name: str, args: list[str]) -> bool:
        code, payload, tail = _cli(args, runner)
        steps.append({"step": name, "code": code, "output": tail[-240:]})
        return code == 0

    known = _cli(["plugin", "marketplace", "list", "--json"], runner)[1]
    entry = next((m for m in (known or []) if isinstance(m, dict) and m.get("name") == NAME), None) if isinstance(known, list) else None
    registered_path = str((entry or {}).get("path") or (entry or {}).get("source") or "")
    if entry and os.path.normcase(os.path.abspath(registered_path)) != os.path.normcase(os.path.abspath(live)):
        # Someone else's marketplace uses our name: do not touch it.
        return write_receipt(runtime_root, {"component": "claude-mod", "action": "install", "ok": False,
                                            "status": "marketplace_name_taken",
                                            "detail": f"Claude Code already has a marketplace called {NAME} from {registered_path}. Neyvia left it alone."})
    ok = step("marketplace_update", ["plugin", "marketplace", "update", NAME]) if entry else step("marketplace_add", ["plugin", "marketplace", "add", live, "--scope", "user"])
    if ok:
        ok = step("plugin_update", ["plugin", "update", PLUGIN_ID, "--scope", "user"]) if before else step("plugin_install", ["plugin", "install", PLUGIN_ID, "--scope", "user"])
    after = installed_plugin(runner, fresh=True) if ok else None
    if not ok or after is None or str(after.get("version") or "") != staged["pluginVersion"]:
        return write_receipt(runtime_root, {"component": "claude-mod", "action": "install", "ok": False, "status": "claude_cli_failed",
                                            "steps": steps, "detail": "Claude Code did not report the expected plugin version afterwards.",
                                            "expectedVersion": staged["pluginVersion"], "claudeVersion": (after or {}).get("version")})
    write_manifest(folder(runtime_root) / "manifest.json", {
        "component": "claude-mod", "pluginVersion": staged["pluginVersion"], "treeSha256": want["treeSha256"],
        "files": staged["files"], "installedAt": now(), "appVersion": app_version(),
        "addedMarketplace": bool(old_mark.get("addedMarketplace")) if old_mark else not entry})
    return write_receipt(runtime_root, {"component": "claude-mod", "action": "update" if before else "install", "ok": True,
                                        "status": "updated" if before else "installed", "steps": steps,
                                        "previousVersion": (before or {}).get("version"), "version": staged["pluginVersion"],
                                        "reload": "In a running Claude Code, type /reload-plugins (or restart it)."})


def remove(runtime_root: str | Path | None = None, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    steps = []
    mark = read_manifest(folder(runtime_root) / "manifest.json")
    if claude_bin():
        if installed_plugin(runner, fresh=True):
            code, _, tail = _cli(["plugin", "uninstall", PLUGIN_ID, "--scope", "user"], runner)
            steps.append({"step": "plugin_uninstall", "code": code, "output": tail[-200:]})
        # Ours when we added it, or when the registered folder is exactly our staged one; never someone else's.
        known = _cli(["plugin", "marketplace", "list", "--json"], runner)[1]
        entry = next((m for m in (known or []) if isinstance(m, dict) and m.get("name") == NAME), None) if isinstance(known, list) else None
        ours = bool(entry) and os.path.normcase(os.path.abspath(str(entry.get("path") or entry.get("source") or ""))) == os.path.normcase(os.path.abspath(str(marketplace_dir(runtime_root))))
        if ours:
            code, _, tail = _cli(["plugin", "marketplace", "remove", NAME], runner)
            steps.append({"step": "marketplace_remove", "code": code, "output": tail[-200:]})
    shutil.rmtree(folder(runtime_root), ignore_errors=True)
    _CACHE["at"] = 0.0
    return write_receipt(runtime_root, {"component": "claude-mod", "action": "remove", "ok": all(s["code"] == 0 for s in steps),
                                        "status": "removed", "steps": steps})
