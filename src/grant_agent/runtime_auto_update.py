from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from .models import RuntimeInstallStatus, utc_now_iso
from .runtimes import (
    detect_runtime_statuses,
    invalidate_runtime_status_cache,
    runtime_adapter_map,
)
from .runtime_updates import compare_version_tokens, latest_npm_release
from .runtimes.base import runtime_subprocess_env
from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_e_sv import enforced

DEFAULT_RUNTIME_UPDATE_IDS = ("openclaw", "hermes", "opencode")
# ``ALL_RUNTIMES`` asks for every installed runtime Neyvia knows (Claude Code, Codex,
# Cursor, OpenCode, Hermes, ...); ones that are not installed are skipped quietly.
ALL_RUNTIMES = "all"
DEFAULT_UPDATE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_UPDATE_TIMEOUT_SECONDS = 900
_NPM_GLOBAL_UPDATE = re.compile(r"\bnpm(?:\.cmd)?\s+(?:install|i)\s+-g\s+(?:--\S+\s+)*((?:@[\w.-]+/)?[\w.-]+)@latest\b")


@enforced("sv.update.package-parse")
def npm_package_of(update_command: str) -> str | None:
    """The package an ``npm install -g <package>@latest`` update command installs."""
    match = _NPM_GLOBAL_UPDATE.search(update_command or "")
    return match.group(1) if match else None


def user_npm_prefix() -> Path | None:
    """The person's own global npm folder (Windows: %APPDATA%\\npm), where their terminal CLIs live."""
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "npm"
    return None


def npm_package_dir(package: str, prefix: str | os.PathLike[str] | None = None) -> Path | None:
    """Where a global npm package is installed under ``prefix`` (default: the person's own npm folder)."""
    base = Path(prefix) if prefix else user_npm_prefix()
    if base is None:
        return None
    folder = (base / "node_modules" if os.name == "nt" else base / "lib" / "node_modules") / Path(*package.split("/"))
    return folder if folder.is_dir() else None


def runtime_in_use(update_command: str, prefix: str | os.PathLike[str] | None = None) -> bool:
    """Whether a program from this runtime's npm package is running now (updating it would fail or break it)."""
    package = npm_package_of(update_command)
    folder = npm_package_dir(package, prefix) if package else None
    if folder is None:
        return False
    marker = str(folder).lower()
    try:
        import psutil
    except ImportError:
        return False
    for process in psutil.process_iter(["exe", "cmdline"]):
        try:
            exe = str(process.info.get("exe") or "").lower()
            cmdline = " ".join(process.info.get("cmdline") or []).lower()
        except (psutil.Error, OSError):
            continue
        if exe.startswith(marker) or marker in cmdline:
            return True
    return False


# Agent CLIs a person may have installed with npm themselves; Neyvia's connected chats use these
# copies (not Neyvia's own managed ones), so they are kept current too. The value is the
# connected-chat app that may hold the CLI open.
USER_GLOBAL_AGENT_CLIS = {
    "@anthropic-ai/claude-code": "claude-code",
    "@openai/codex": "codex",
    "opencode-ai": None,
    "@google/gemini-cli": None,
    "openclaw": None,
}


def tool_update_admission(root: Path) -> dict[str, Any]:
    """An environment opt-in cannot override owner policy or a disposable checkout."""
    from .ui_command_bus import bus_for
    root = Path(root).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    disposable = root.is_relative_to(temporary) or any(
        part.name.casefold() in {".agent_control", "scratch", "dev", "test", "tests"}
        or part.name.casefold().startswith("nx-") or (part / ".git").is_file()
        for part in (root, *root.parents))
    settings = bus_for(root).get("settings", {})
    policy = settings.get("toolAutoUpdate", "allow")
    reason = ("development_or_scratch_root" if disposable else "local_only" if settings.get("localOnly") else
              "updates_disabled" if policy == "off" else "owner_approval_required" if policy != "allow" else
              "disabled_by_environment" if os.environ.get("NEYVIA_TOOL_AUTO_UPDATE", "1").lower() in {"0", "false", "off", "no"} else "owner_allowed")
    return {"allowed": reason == "owner_allowed", "policy": policy, "reason": reason,
            "message": "Global CLI updates are disabled in development and scratch roots." if disposable else
            "Set toolAutoUpdate to allow in owner-approved Settings before automatic CLI updates." if policy == "ask" else reason.replace("_", " ")}


def record_tool_update(root: Path, receipt: dict[str, Any]) -> None:
    """Keep a compact shared activity event; full details remain in the update receipt."""
    from .ui_command_bus import bus_for
    bus = bus_for(root)
    activity = {"status": receipt.get("status"), "reason": receipt.get("reason"),
                "updatedCount": receipt.get("updatedCount", 0),
                "packages": [{key: row[key] for key in ("package", "before", "after", "status") if key in row}
                             for row in receipt.get("clis", [])]}
    previous = bus.get("tool.update.last", {})
    if activity.get("status") == "blocked" and previous == activity:
        return
    bus.put("tool.update.last", activity)
    bus.emit("tool.update", activity)
    bus.emit("notify", {"level": "info" if activity["status"] == "blocked" else "success" if activity["status"] == "passed" else "warning",
                        "message": receipt.get("message") or f"CLI updates: {activity['updatedCount']} updated; {activity['status']}"})


def blocked_tool_update(root: Path, admission: dict[str, Any]) -> dict[str, Any]:
    receipt = {"schema": "neyvia.user_cli_update.v1", "completedAt": utc_now_iso(), "status": "blocked",
               **admission, "updatedCount": 0, "clis": []}
    record_tool_update(root, receipt)
    return receipt


def keep_tools_updated(backend, *, first_delay: float = 600, round_seconds: float = 3600) -> None:
    """Every round checks the current owner setting before starting network or child work."""
    if os.environ.get("NEYVIA_TOOL_AUTO_UPDATE", "1").lower() in {"0", "false", "off", "no"}:
        return
    time.sleep(first_delay)
    while True:
        try:
            admission = tool_update_admission(backend.root)
            if not admission["allowed"]:
                blocked_tool_update(backend.root, admission)
            else:
                from .connected_sessions.broker import broker_for
                broker = broker_for(backend.root, backend)
                prefix = runtime_subprocess_env(backend.root).get("NPM_CONFIG_PREFIX")
                update_user_global_clis(backend.root, release=broker.release_for_update)
                from .connections_install import PACKAGES, update_installed
                from .cli_installer import load_manifest
                update_installed(backend.root)
                apps = {"codex": "codex", "claude-code": "claude-code"}
                ids = [ident for ident in runtime_adapter_map() if ident not in PACKAGES or not load_manifest(ident)]
                ensure_runtime_auto_update(backend.root, runtime_ids=ids, skip_missing=True,
                    in_use=lambda identity, command: runtime_in_use(command, prefix),
                    release=lambda identity: identity in apps and broker.release_for_update(apps[identity]))
        except Exception as exc:
            print(f"Tool update round failed: {exc}", flush=True)
        time.sleep(round_seconds)


def user_cli_update_receipt_path(root: Path) -> Path:
    return Path(root) / ".agent_control" / "user_cli_update.json"


def _installed_npm_version(package: str, prefix: Path) -> str | None:
    folder = npm_package_dir(package, prefix)
    try:
        return str(json.loads((folder / "package.json").read_text(encoding="utf-8")).get("version") or "") or None if folder else None
    except (OSError, ValueError):
        return None


def update_user_global_clis(
    root: Path,
    *,
    packages: dict[str, str | None] | None = None,
    in_use: Callable[[str, Path], bool] | None = None,
    release: Callable[[str], bool] | None = None,
    dry_run: bool = False,
    timeout_seconds: int = DEFAULT_UPDATE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Bring the person's own npm-installed agent CLIs to their newest release, one by one.

    Only packages already installed are touched; a busy one (a Claude Code session, the Codex
    app-server) is left for the next round unless ``release(app)`` frees it.
    """
    root = Path(root).resolve()
    admission = tool_update_admission(root)
    if not admission["allowed"]:
        return blocked_tool_update(root, admission)
    prefix = user_npm_prefix()
    rows: list[dict[str, Any]] = []
    for package, app in (packages or USER_GLOBAL_AGENT_CLIS).items():
        admission = tool_update_admission(root)
        if not admission["allowed"]:
            rows.append({"package": package, "status": "blocked", "reason": admission["reason"]})
            break
        if prefix is None:
            break
        installed = _installed_npm_version(package, prefix)
        if not installed:
            continue
        latest = str(latest_npm_release(package).get("version") or "")
        row: dict[str, Any] = {"package": package, "before": installed, "latest": latest or None}
        command = f"npm install -g {package}@latest"
        if not latest or compare_version_tokens(installed, latest) >= 0:
            rows.append({**row, "status": "skipped", "reason": "already_current" if latest else "latest_version_unknown"})
            continue
        if dry_run:
            rows.append({**row, "status": "planned", "command": command})
            continue
        busy = in_use or (lambda command_text, where: runtime_in_use(command_text, where))
        if busy(command, prefix) and (not app or release is None or not release(app) or busy(command, prefix)):
            rows.append({**row, "status": "deferred", "reason": "in_use_retry_later"})
            continue
        env = {key: value for key, value in os.environ.items() if key.upper() != "NPM_CONFIG_PREFIX"}
        admission = tool_update_admission(root)
        if not admission["allowed"]:
            rows.append({**row, "status": "blocked", "reason": admission["reason"]})
            break
        started = time.monotonic()
        try:
            done = subprocess.run(command, shell=True, cwd=str(Path.home()), env=env, capture_output=True,
                                  stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                  timeout=timeout_seconds, check=False, **hidden_windows_subprocess_kwargs())
            after = _installed_npm_version(package, prefix)
            ok = done.returncode == 0 and after is not None and compare_version_tokens(after, latest) >= 0
            rows.append({**row, "status": "updated" if ok else "failed", "after": after, "exitCode": done.returncode,
                         "reason": "update_command_completed" if ok else "update_command_failed",
                         "stderrPreview": _preview(done.stderr), "durationMs": int((time.monotonic() - started) * 1000)})
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append({**row, "status": "failed", "reason": f"update_launch_failed: {exc}"})
    receipt = {
        "schema": "neyvia.user_cli_update.v1",
        "completedAt": utc_now_iso(),
        "prefix": str(prefix) if prefix else None,
        "status": "blocked" if any(r["status"] == "blocked" for r in rows)
        else "failed" if any(r["status"] == "failed" for r in rows)
        else ("deferred" if any(r["status"] == "deferred" for r in rows) else "passed"),
        "updatedCount": sum(1 for r in rows if r["status"] == "updated"),
        "clis": rows,
    }
    if not dry_run:
        target = user_cli_update_receipt_path(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        record_tool_update(root, receipt)
    return receipt


def _update_needed(status: RuntimeInstallStatus, update_command: str) -> tuple[bool, str, str | None]:
    """(update?, reason, latest version) for one runtime.

    Runtimes that compare versions themselves report ``update_available``. For an npm-installed
    CLI that does not, the newest npm release is compared with the installed version.
    """
    if status.update_available:
        return True, "update_reported", status.latest_version
    package = npm_package_of(update_command)
    if package and status.version:
        latest = str(latest_npm_release(package).get("version") or "")
        if latest and compare_version_tokens(status.version, latest) < 0:
            return True, "newer_npm_release", latest
        return False, "already_current" if latest else "latest_version_unknown", latest or None
    return False, "already_current_or_update_not_reported", None


def runtime_auto_update_receipt_path(root: Path) -> Path:
    return root / ".agent_control" / "runtime_update_preflight.json"


def latest_runtime_auto_update_receipt(root: Path) -> dict[str, Any]:
    path = runtime_auto_update_receipt_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def ensure_runtime_auto_update(
    root: Path,
    *,
    runtime_ids: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
    dry_run: bool = False,
    ttl_seconds: int = DEFAULT_UPDATE_TTL_SECONDS,
    timeout_seconds: int = DEFAULT_UPDATE_TIMEOUT_SECONDS,
    extra_env: dict[str, str] | None = None,
    skip_missing: bool = False,
    in_use: Callable[[str, str], bool] | None = None,
    release: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Update runtimes that have a newer version, and write a receipt.

    ``skip_missing`` reports runtimes that are not installed as skipped, not failed.
    ``in_use(runtime_id, update_command)`` says a runtime is busy: it is skipped this time and
    the receipt is marked ``deferred`` so the next round retries it. ``release(runtime_id)``
    may free a runtime Neyvia itself holds open (for example an idle Codex app-server) first.
    """
    root = Path(root).resolve()
    requested = runtime_ids or DEFAULT_RUNTIME_UPDATE_IDS
    if isinstance(requested, str):
        requested = (requested,)
    if any(_normalize_runtime_id(item) == ALL_RUNTIMES for item in requested):
        requested = tuple(runtime_adapter_map().keys())
    runtime_ids = tuple(
        _normalize_runtime_id(item)
        for item in requested
        if _normalize_runtime_id(item)
    )
    if not force and not dry_run and ttl_seconds > 0:
        cached = latest_runtime_auto_update_receipt(root)
        if _receipt_is_fresh(cached, ttl_seconds=ttl_seconds):
            cached = dict(cached)
            cached["cacheHit"] = True
            cached["skippedReason"] = "recent_successful_preflight"
            return cached

    started_at = utc_now_iso()
    started = time.monotonic()
    adapters = runtime_adapter_map()
    before_statuses = {
        item.runtime_id: item
        for item in detect_runtime_statuses(root, force=True)
        if item.runtime_id in runtime_ids
    }
    rows: list[dict[str, Any]] = []
    for runtime_id in runtime_ids:
        adapter = adapters.get(runtime_id)
        before_status = before_statuses.get(runtime_id)
        if adapter is None:
            rows.append(
                _runtime_update_row(
                    runtime_id=runtime_id,
                    status="failed",
                    reason="unknown_runtime",
                    before=before_status,
                )
            )
            continue
        if before_status is None:
            try:
                before_status = adapter.doctor(root)
            except Exception as exc:  # pragma: no cover - defensive runtime failure
                rows.append(
                    _runtime_update_row(
                        runtime_id=runtime_id,
                        status="failed",
                        reason=f"doctor_failed: {exc}",
                    )
                )
                continue
        if not before_status.detected:
            rows.append(
                _runtime_update_row(
                    runtime_id=runtime_id,
                    status="skipped" if skip_missing else "failed",
                    reason="not_installed" if skip_missing else "runtime_not_detected",
                    before=before_status,
                )
            )
            continue
        update = adapter.update(root)
        command = str(update.get("command") or "").strip()
        needed, why, latest = _update_needed(before_status, command)
        if not force and not needed:
            rows.append(
                _runtime_update_row(
                    runtime_id=runtime_id,
                    status="skipped",
                    reason=why,
                    before=before_status,
                )
            )
            continue
        if not dry_run and in_use is not None and in_use(runtime_id, command):
            if release is None or not release(runtime_id) or in_use(runtime_id, command):
                rows.append(
                    _runtime_update_row(
                        runtime_id=runtime_id,
                        status="deferred",
                        reason="in_use_retry_later",
                        before=before_status,
                        command=command,
                    )
                )
                continue
        if not command:
            rows.append(
                _runtime_update_row(
                    runtime_id=runtime_id,
                    status="failed",
                    reason="missing_update_command",
                    before=before_status,
                )
            )
            continue
        if dry_run:
            rows.append(
                _runtime_update_row(
                    runtime_id=runtime_id,
                    status="planned",
                    reason="dry_run",
                    before=before_status,
                    command=command,
                    follow_up=str(update.get("follow_up") or ""),
                )
            )
            continue
        rows.append(
            _run_runtime_update_command(
                root,
                runtime_id=runtime_id,
                command=command,
                follow_up=str(update.get("follow_up") or ""),
                before=before_status,
                timeout_seconds=timeout_seconds,
                extra_env=extra_env or {},
            )
        )

    invalidate_runtime_status_cache(root)
    for row in rows:
        if row.get("status") == "updated":
            package = npm_package_of(str(row.get("command") or ""))
            if package:
                from .runtime_updates import _CACHE
                _CACHE.pop(f"npm:{package}", None)
    after_status_objects = {
        item.runtime_id: item
        for item in detect_runtime_statuses(root, force=True)
        if item.runtime_id in runtime_ids
    }
    for row in rows:
        if row.get("status") != "updated":
            continue
        runtime_id = str(row.get("runtimeId") or "")
        after_status = after_status_objects.get(runtime_id)
        row["after"] = asdict(after_status) if after_status is not None else {}
        if after_status is None:
            row["status"] = "failed"
            row["reason"] = "update_completed_but_after_status_missing"
        elif _update_needed(after_status, str(row.get("command") or ""))[0]:
            row["status"] = "failed"
            row["reason"] = "update_completed_but_runtime_still_reports_update_available"
    after_statuses = {
        runtime_id: asdict(item)
        for runtime_id, item in after_status_objects.items()
    }
    failed = [row for row in rows if row.get("status") == "failed"]
    planned = [row for row in rows if row.get("status") == "planned"]
    executed = [row for row in rows if row.get("status") == "updated"]
    deferred = [row for row in rows if row.get("status") == "deferred"]
    receipt = {
        "schema": "fluxio.runtime_auto_update.v1",
        "receiptId": f"runtime_update_{uuid.uuid4().hex[:10]}",
        "startedAt": started_at,
        "completedAt": utc_now_iso(),
        "root": str(root),
        "runtimeIds": list(runtime_ids),
        "force": bool(force),
        "dryRun": bool(dry_run),
        "status": (
            "failed"
            if failed
            else ("planned" if planned else ("deferred" if deferred else "passed"))
        ),
        "updatedCount": len(executed),
        "deferredCount": len(deferred),
        "failedCount": len(failed),
        "skippedCount": len([row for row in rows if row.get("status") == "skipped"]),
        "durationMs": int((time.monotonic() - started) * 1000),
        "runtimes": rows,
        "afterRuntimeStatuses": after_statuses,
    }
    if not dry_run:
        path = runtime_auto_update_receipt_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def _run_runtime_update_command(
    root: Path,
    *,
    runtime_id: str,
    command: str,
    follow_up: str,
    before: RuntimeInstallStatus,
    timeout_seconds: int,
    extra_env: dict[str, str],
) -> dict[str, Any]:
    env = runtime_subprocess_env(root)
    env.update(extra_env)
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            shell=True,
            cwd=str(root),
            env=env,
            capture_output=True,
            stdin=subprocess.DEVNULL,  # an updater that asks a question gets no answer instead of hanging
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        return _runtime_update_row(
            runtime_id=runtime_id,
            status="failed",
            reason=f"update_timed_out_after_{timeout_seconds}s",
            before=before,
            command=command,
            follow_up=follow_up,
            duration_ms=int((time.monotonic() - started) * 1000),
            stdout=_preview(exc.stdout),
            stderr=_preview(exc.stderr),
            exit_code=124,
        )
    except OSError as exc:
        return _runtime_update_row(
            runtime_id=runtime_id,
            status="failed",
            reason=f"update_launch_failed: {exc}",
            before=before,
            command=command,
            follow_up=follow_up,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return _runtime_update_row(
        runtime_id=runtime_id,
        status="updated" if completed.returncode == 0 else "failed",
        reason="update_command_completed" if completed.returncode == 0 else "update_command_failed",
        before=before,
        command=command,
        follow_up=follow_up,
        duration_ms=int((time.monotonic() - started) * 1000),
        stdout=_preview(completed.stdout),
        stderr=_preview(completed.stderr),
        exit_code=completed.returncode,
    )


def _runtime_update_row(
    *,
    runtime_id: str,
    status: str,
    reason: str,
    before: RuntimeInstallStatus | None = None,
    command: str = "",
    follow_up: str = "",
    duration_ms: int = 0,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    return {
        "runtimeId": runtime_id,
        "status": status,
        "reason": reason,
        "command": command,
        "followUp": follow_up,
        "exitCode": exit_code,
        "durationMs": duration_ms,
        "stdoutPreview": stdout,
        "stderrPreview": stderr,
        "before": asdict(before) if before is not None else {},
    }


def _receipt_is_fresh(receipt: dict[str, Any], *, ttl_seconds: int) -> bool:
    if not receipt or receipt.get("status") != "passed":
        return False
    completed_at = str(receipt.get("completedAt") or "")
    if not completed_at:
        return False
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    age_seconds = time.time() - parsed.timestamp()
    return 0 <= age_seconds <= ttl_seconds


def _normalize_runtime_id(value: object) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "open-code": "opencode",
        "opencode-native": "opencode",
        "openclaw-local": "openclaw",
    }
    return aliases.get(normalized, normalized)


def _preview(value: object, limit: int = 1200) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:limit]
