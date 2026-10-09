from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .platform_config import platform_config
from .subprocess_utils import hidden_windows_subprocess_kwargs


PROOF_STATUS_SCHEMA = "fluxio.real_agent_runtime_proof_status.v1"
PROOF_RUN_SCHEMA = "fluxio.real_agent_runtime_proof_run.v1"
MIXED_PROOF_SCHEMA = "fluxio.real_agent_mixed_runtime_proof.v1"
PROOF_EVIDENCE_RECEIPT_SCHEMA = "fluxio.real_agent_proof_evidence_receipt.v1"
PROOF_SCREENSHOT_RECEIPT_SCHEMA = "fluxio.real_agent_proof_screenshot_receipt.v1"
PROOF_EVIDENCE_HEALTH_SCHEMA = "fluxio.real_agent_proof_evidence_health.v1"
PROOF_EVIDENCE_CHECKLIST_SCHEMA = "fluxio.real_agent_proof_evidence_checklist.v1"
PROOF_RUN_TIMELINE_SCHEMA = "fluxio.real_agent_proof_run_timeline.v1"
PROOF_NEXT_TARGET_SCHEMA = "fluxio.real_agent_proof_next_target.v1"
PROOF_ACTION_COMMAND_SCHEMA = "fluxio.real_agent_proof_action_command.v1"
PROOF_TRANSCRIPT_RECEIPT_SCHEMA = "fluxio.real_agent_transcript_receipt.v1"
PROOF_TRANSCRIPT_HEALTH_SCHEMA = "fluxio.real_agent_transcript_health.v1"
PROOF_RUN_LOCK_SCHEMA = "fluxio.real_agent_proof_run_lock.v1"
PROOF_REPORT_INDEX_SCHEMA = "fluxio.real_agent_proof_report_index.v1"
PROOF_RECEIPT_CACHE_SCHEMA = "fluxio.real_agent_proof_receipt_cache.v1"
PROOF_STALE_AFTER_SECONDS = 24 * 60 * 60
PROOF_RUN_LOCK_STALE_SECONDS = 30 * 60
PROOF_REPORT_INDEX_MAX_PATHS = 24
PROOF_RECEIPT_CACHE_MAX_ENTRIES = 512
SUPPORTED_PROOF_RUNTIMES = {"hermes", "openclaw", "mixed"}
PROOF_COMMAND_TIMEOUTS = {
    "hermes": 120,
    "openclaw": 90,
    "mixed": 120,
}
RUNTIME_BAG_IDS = {
    "hermes": "fresh_hermes_round",
    "openclaw": "fresh_openclaw_round",
}
MIXED_REQUIRED_RUNTIME_IDS = ("hermes", "openclaw")
PROOF_SCREENSHOT_REQUIREMENTS = (
    {
        "key": "agent_ui_screenshot",
        "label": "Agent UI screenshot",
        "aliases": {"agent_ui_screenshot", "agentConversation"},
    },
    {
        "key": "produced_output_preview",
        "label": "Produced output Preview screenshot",
        "aliases": {
            "produced_output_preview",
            "producedOutputPreview",
            "agentPreviewAfterClick",
            "previewAfterClick",
            "agentPreviewWindow",
        },
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _proof_freshness_fields(report: dict[str, Any]) -> dict[str, Any]:
    timestamp = report.get("createdAt") or report.get("checkedAt") or ""
    parsed = _parse_utc_datetime(timestamp)
    if parsed is None:
        return {
            "proofFreshness": "unknown",
            "proofAgeSeconds": None,
            "stale": False,
            "staleAfterSeconds": PROOF_STALE_AFTER_SECONDS,
        }
    age_seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    stale = age_seconds > PROOF_STALE_AFTER_SECONDS
    return {
        "proofFreshness": "stale" if stale else "fresh",
        "proofAgeSeconds": age_seconds,
        "stale": stale,
        "staleAfterSeconds": PROOF_STALE_AFTER_SECONDS,
    }


def _safe_int(value: object, default: int, *, minimum: int = 1, maximum: int = 900) -> int:
    try:
        return min(maximum, max(minimum, int(value)))
    except (TypeError, ValueError):
        return min(maximum, max(minimum, default))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(6)}")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def proof_out_dir(root: Path) -> Path:
    return Path(root).resolve() / "tmp-ui-checks" / "real-agent-conversation-proof"


def proof_run_lock_path(root: Path) -> Path:
    return proof_out_dir(root) / "real-agent-proof-run.lock.json"


def proof_report_index_path(root: Path) -> Path:
    return Path(root).resolve() / ".agent_control" / "real_agent_proof_report_index.json"


def proof_receipt_cache_path(root: Path) -> Path:
    return Path(root).resolve() / ".agent_control" / "real_agent_proof_receipt_cache.json"


def _split_configured_roots(value: str) -> list[str]:
    if not value:
        return []
    separator = ";" if ";" in value else os.pathsep
    return [item.strip() for item in value.replace("\n", separator).split(separator) if item.strip()]


def _append_existing_root(candidates: list[Path], value: object) -> None:
    text = str(value or "").strip()
    if not text:
        return
    path = Path(text).expanduser()
    if path.exists() and path.is_dir():
        candidates.append(path)


def _configured_workspace_proof_roots(root: Path) -> list[Path]:
    workspaces_path = Path(root).resolve() / ".agent_control" / "workspaces.json"
    try:
        payload = json.loads(workspaces_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload if isinstance(payload, list) else []
    candidates: list[Path] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_text = " ".join(
            str(row.get(key) or "")
            for key in ("name", "root_path", "local_project_path", "nas_project_path", "sync_mode")
        ).lower()
        if "vibe-coding-platform" not in row_text:
            continue
        for key in ("nas_project_path", "root_path", "local_project_path"):
            _append_existing_root(candidates, row.get(key))
    return candidates


def _candidate_proof_roots(root: Path) -> list[Path]:
    root = Path(root).resolve()
    candidates: list[Path] = [root]
    for raw_path in _split_configured_roots(
        os.environ.get("FLUXIO_REAL_AGENT_PROOF_ROOTS", "")
        or os.environ.get("FLUXIO_PROOF_ROOTS", "")
    ):
        _append_existing_root(candidates, raw_path)
    candidates.extend(_configured_workspace_proof_roots(root))
    normalized_root = str(root).replace("\\", "/")
    config = platform_config(root)
    releases_root = str(config.nas_projects_root / "syntelos" / "releases").replace("\\", "/")
    if f"{releases_root}/" in normalized_root:
        _append_existing_root(candidates, config.nas_project_root)

    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).replace("\\", "/").lower()
        if key in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(key)
        roots.append(resolved)
    return roots or [root]


def _owner_root_for_path(path: Path, source_roots: list[Path], default_root: Path) -> Path:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for candidate in source_roots:
        try:
            resolved.relative_to(candidate.resolve())
            return candidate.resolve()
        except (OSError, ValueError):
            continue
    return default_root.resolve()


def _index_path_value(root: Path, path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        return str(resolved.relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _resolve_index_path(root: Path, value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = Path(root).resolve() / path
    if not path.exists() or not path.is_file():
        return None
    return path


def _load_proof_report_index(root: Path) -> tuple[list[Path], dict[str, Any]]:
    index_path = proof_report_index_path(root)
    payload = _read_json(index_path)
    if payload.get("schema") != PROOF_REPORT_INDEX_SCHEMA:
        return [], {
            "schema": PROOF_REPORT_INDEX_SCHEMA,
            "status": "miss",
            "indexPath": str(index_path),
            "indexedPathCount": 0,
        }
    raw_paths = payload.get("reportPaths") if isinstance(payload.get("reportPaths"), list) else []
    paths: list[Path] = []
    seen: set[str] = set()
    for value in raw_paths:
        path = _resolve_index_path(root, value)
        if path is None:
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths, {
        "schema": PROOF_REPORT_INDEX_SCHEMA,
        "status": "hit" if paths else "empty",
        "indexPath": str(index_path),
        "indexedPathCount": len(paths),
        "writtenAt": str(payload.get("writtenAt") or ""),
        "latestReportPath": str(payload.get("latestReportPath") or ""),
        "latestCompleteReportPath": str(payload.get("latestCompleteReportPath") or ""),
    }


def _load_proof_receipt_cache(root: Path) -> dict[str, Any]:
    cache_path = proof_receipt_cache_path(root)
    payload = _read_json(cache_path)
    raw_entries = payload.get("entries") if isinstance(payload.get("entries"), dict) else {}
    entries = raw_entries if payload.get("schema") == PROOF_RECEIPT_CACHE_SCHEMA else {}
    return {
        "schema": PROOF_RECEIPT_CACHE_SCHEMA,
        "status": "hit" if entries else "miss",
        "cachePath": str(cache_path),
        "entryCount": len(entries),
        "hitCount": 0,
        "missCount": 0,
        "writeCount": 0,
        "_root": Path(root).resolve(),
        "_entries": dict(entries),
        "_dirty": False,
    }


def _proof_receipt_cache_key(receipt_cache: dict[str, Any], path: Path) -> str:
    root = receipt_cache.get("_root")
    if isinstance(root, Path):
        return _index_path_value(root, path)
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _proof_receipt_cache_hit(
    receipt_cache: dict[str, Any] | None,
    path: Path,
    *,
    size_bytes: int,
    modified_at: str,
) -> dict[str, Any]:
    if not isinstance(receipt_cache, dict):
        return {}
    entries = receipt_cache.get("_entries") if isinstance(receipt_cache.get("_entries"), dict) else {}
    entry = entries.get(_proof_receipt_cache_key(receipt_cache, path))
    if (
        isinstance(entry, dict)
        and int(entry.get("sizeBytes") or -1) == size_bytes
        and str(entry.get("modifiedAt") or "") == modified_at
        and str(entry.get("sha256") or "").strip()
    ):
        receipt_cache["hitCount"] = int(receipt_cache.get("hitCount") or 0) + 1
        return entry
    receipt_cache["missCount"] = int(receipt_cache.get("missCount") or 0) + 1
    return {}


def _store_proof_receipt_cache_entry(
    receipt_cache: dict[str, Any] | None,
    path: Path,
    *,
    size_bytes: int,
    modified_at: str,
    sha256: str,
) -> None:
    if not isinstance(receipt_cache, dict) or not sha256:
        return
    entries = receipt_cache.get("_entries")
    if not isinstance(entries, dict):
        entries = {}
        receipt_cache["_entries"] = entries
    key = _proof_receipt_cache_key(receipt_cache, path)
    entries[key] = {
        "path": key,
        "sizeBytes": size_bytes,
        "modifiedAt": modified_at,
        "sha256": sha256,
        "cachedAt": _utc_now(),
    }
    receipt_cache["writeCount"] = int(receipt_cache.get("writeCount") or 0) + 1
    receipt_cache["_dirty"] = True


def _write_proof_receipt_cache(root: Path, receipt_cache: dict[str, Any]) -> None:
    if not isinstance(receipt_cache, dict) or not receipt_cache.get("_dirty"):
        return
    entries = receipt_cache.get("_entries") if isinstance(receipt_cache.get("_entries"), dict) else {}
    sorted_entries = sorted(
        entries.items(),
        key=lambda item: (
            str(item[1].get("cachedAt") or ""),
            str(item[1].get("modifiedAt") or ""),
            str(item[0]),
        ),
        reverse=True,
    )
    pruned_entries = dict(sorted_entries[:PROOF_RECEIPT_CACHE_MAX_ENTRIES])
    _write_json(
        proof_receipt_cache_path(root),
        {
            "schema": PROOF_RECEIPT_CACHE_SCHEMA,
            "writtenAt": _utc_now(),
            "root": str(Path(root).resolve()),
            "entries": pruned_entries,
        },
    )
    receipt_cache["_entries"] = pruned_entries
    receipt_cache["entryCount"] = len(pruned_entries)
    receipt_cache["_dirty"] = False


def _proof_receipt_cache_status(receipt_cache: dict[str, Any]) -> dict[str, Any]:
    entries = receipt_cache.get("_entries") if isinstance(receipt_cache.get("_entries"), dict) else {}
    return {
        "schema": PROOF_RECEIPT_CACHE_SCHEMA,
        "status": str(receipt_cache.get("status") or "miss"),
        "cachePath": str(receipt_cache.get("cachePath") or ""),
        "entryCount": len(entries),
        "hitCount": int(receipt_cache.get("hitCount") or 0),
        "missCount": int(receipt_cache.get("missCount") or 0),
        "writeCount": int(receipt_cache.get("writeCount") or 0),
        "maxEntries": PROOF_RECEIPT_CACHE_MAX_ENTRIES,
    }


def _write_proof_report_index(
    root: Path,
    *,
    report_summaries: list[dict[str, Any]],
    proof_run_timeline: dict[str, Any],
    latest_summary: dict[str, Any],
    latest_screenshot_summary: dict[str, Any],
    latest_complete_summary: dict[str, Any],
    latest_transcript_summary: dict[str, Any],
) -> None:
    path_values: list[str] = []

    def add_path(value: object) -> None:
        text = str(value or "").strip()
        if not text:
            return
        path = Path(text)
        if not path.is_absolute():
            path = Path(root).resolve() / path
        if not path.exists() or not path.is_file():
            return
        indexed = _index_path_value(root, path)
        if indexed not in path_values:
            path_values.append(indexed)

    for summary in [
        latest_summary,
        latest_screenshot_summary,
        latest_complete_summary,
        latest_transcript_summary,
    ]:
        if isinstance(summary, dict):
            add_path(summary.get("reportPath"))
    for row in proof_run_timeline.get("rows", []) if isinstance(proof_run_timeline.get("rows"), list) else []:
        if isinstance(row, dict):
            add_path(row.get("reportPath"))
    for summary in report_summaries[:PROOF_REPORT_INDEX_MAX_PATHS]:
        add_path(summary.get("reportPath"))
    payload = {
        "schema": PROOF_REPORT_INDEX_SCHEMA,
        "writtenAt": _utc_now(),
        "root": str(Path(root).resolve()),
        "reportPaths": path_values[:PROOF_REPORT_INDEX_MAX_PATHS],
        "latestReportPath": latest_summary.get("reportPath") if isinstance(latest_summary, dict) else "",
        "latestCompleteReportPath": latest_complete_summary.get("reportPath") if isinstance(latest_complete_summary, dict) else "",
        "latestScreenshotReportPath": latest_screenshot_summary.get("reportPath") if isinstance(latest_screenshot_summary, dict) else "",
        "latestTranscriptReportPath": latest_transcript_summary.get("reportPath") if isinstance(latest_transcript_summary, dict) else "",
        "timelineReportCount": len(proof_run_timeline.get("rows", [])) if isinstance(proof_run_timeline.get("rows"), list) else 0,
    }
    _write_json(proof_report_index_path(root), payload)


def _proof_run_lock_status(root: Path) -> dict[str, Any]:
    lock_path = proof_run_lock_path(root)
    lock = _read_json(lock_path) if lock_path.exists() else {}
    if not lock:
        return {
            "schema": PROOF_RUN_LOCK_SCHEMA,
            "status": "idle",
            "running": False,
            "lockPath": str(lock_path),
            "runtime": "",
            "createdAt": "",
            "ageSeconds": 0,
            "staleAfterSeconds": PROOF_RUN_LOCK_STALE_SECONDS,
            "stale": False,
        }
    created = _parse_utc_datetime(lock.get("createdAt"))
    age_seconds = 0
    if created is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - created).total_seconds()))
    stale_after = _safe_int(
        lock.get("staleAfterSeconds"),
        PROOF_RUN_LOCK_STALE_SECONDS,
        minimum=60,
        maximum=6 * 60 * 60,
    )
    stale = created is None or age_seconds > stale_after
    return {
        "schema": PROOF_RUN_LOCK_SCHEMA,
        "status": "stale" if stale else "running",
        "running": not stale,
        "lockPath": str(lock_path),
        "runtime": str(lock.get("runtime") or ""),
        "requestedRuntime": str(lock.get("runtime") or ""),
        "createdAt": str(lock.get("createdAt") or ""),
        "ageSeconds": age_seconds,
        "staleAfterSeconds": stale_after,
        "stale": stale,
        "pid": lock.get("pid") or 0,
        "token": str(lock.get("token") or ""),
        "withBrowser": bool(lock.get("withBrowser")),
        "runtimeTimeout": int(lock.get("runtimeTimeout") or 0),
    }


def _clear_stale_proof_run_lock(root: Path) -> None:
    status = _proof_run_lock_status(root)
    if not status.get("stale"):
        return
    try:
        proof_run_lock_path(root).unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _acquire_proof_run_lock(
    root: Path,
    *,
    runtime: str,
    runtime_timeout: int,
    with_browser: bool,
) -> tuple[dict[str, Any], bool]:
    root = Path(root).resolve()
    _clear_stale_proof_run_lock(root)
    lock_path = proof_run_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(12)
    payload = {
        "schema": PROOF_RUN_LOCK_SCHEMA,
        "status": "running",
        "running": True,
        "root": str(root),
        "runtime": runtime,
        "runtimeTimeout": runtime_timeout,
        "withBrowser": bool(with_browser),
        "pid": os.getpid(),
        "createdAt": _utc_now(),
        "staleAfterSeconds": PROOF_RUN_LOCK_STALE_SECONDS,
        "token": token,
        "lockPath": str(lock_path),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock_path), flags)
    except FileExistsError:
        return _proof_run_lock_status(root), False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        try:
            lock_path.unlink()
        except OSError:
            pass
        raise
    return payload, True


def _release_proof_run_lock(root: Path, lock: dict[str, Any]) -> None:
    lock_path = proof_run_lock_path(root)
    current = _read_json(lock_path) if lock_path.exists() else {}
    if str(current.get("token") or "") != str(lock.get("token") or ""):
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _proof_run_already_running_payload(root: Path, runtime: str, lock_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": PROOF_RUN_SCHEMA,
        "runtime": runtime,
        "status": "running",
        "ok": False,
        "alreadyRunning": True,
        "lock": lock_status,
        "headline": "A real-agent proof run is already in progress for this workspace.",
        "nextAction": "Wait for the active proof run to finish, then refresh the real runtime proof status.",
        "proofStatus": {
            **build_real_agent_proof_status(root),
            "proofRunLock": lock_status,
            "proofRunInProgress": True,
        },
    }


def _parse_json_payload(stdout: str, stderr: str) -> dict[str, Any]:
    body = (stdout or "").strip() or (stderr or "").strip()
    if not body:
        return {}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r"(\{(?:.|\n)*\})", body)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _created_sort_key(report: dict[str, Any], path: Path | None = None) -> tuple[str, float]:
    created = str(report.get("createdAt") or report.get("checkedAt") or "")
    mtime = 0.0
    if path is not None:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
    return created, mtime


def _preferred_report_path(report: dict[str, Any], source_path: Path) -> Path:
    raw_path = str(report.get("reportPath") or "").strip()
    if raw_path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = source_path.parent / candidate
        if candidate.exists():
            return candidate
    return source_path


def _logical_report_key(report: dict[str, Any], report_path: Path) -> str:
    runtime_ids = ",".join(_report_runtime_ids(report) or [str(report.get("runtime") or "")])
    return "|".join(
        [
            str(report.get("schema") or ""),
            str(report.get("createdAt") or report.get("checkedAt") or ""),
            runtime_ids,
            str(report_path).replace("\\", "/").lower(),
        ]
    )


def _local_evidence_receipt(
    selected_path: Path | None,
    *,
    schema: str,
    path_key: str,
    missing_path_status: str,
    missing_file_status: str,
    source: str,
    extra: dict[str, Any] | None = None,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": schema,
        path_key: str(selected_path or ""),
        "exists": False,
        "sizeBytes": 0,
        "sha256": "",
        "modifiedAt": "",
        "status": missing_path_status if selected_path is None else missing_file_status,
        "source": source,
    }
    receipt.update(extra or {})
    if selected_path is None:
        return receipt
    try:
        stat = selected_path.stat()
    except OSError:
        return receipt
    if not selected_path.is_file():
        receipt["status"] = "not_a_file"
        return receipt
    size_bytes = int(stat.st_size)
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    cached = _proof_receipt_cache_hit(
        receipt_cache,
        selected_path,
        size_bytes=size_bytes,
        modified_at=modified_at,
    )
    if cached:
        receipt.update(
            {
                "exists": True,
                "sizeBytes": size_bytes,
                "sha256": str(cached.get("sha256") or ""),
                "modifiedAt": modified_at,
                "status": "attached",
                "receiptCache": "hit",
            }
        )
        return receipt
    digest = hashlib.sha256()
    try:
        with selected_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        receipt["status"] = "unreadable"
        receipt["error"] = _compact_problem_text(exc)
        return receipt
    receipt.update(
        {
            "exists": True,
            "sizeBytes": size_bytes,
            "sha256": digest.hexdigest(),
            "modifiedAt": modified_at,
            "status": "attached",
            "receiptCache": "miss",
        }
    )
    _store_proof_receipt_cache_entry(
        receipt_cache,
        selected_path,
        size_bytes=size_bytes,
        modified_at=modified_at,
        sha256=str(receipt.get("sha256") or ""),
    )
    return receipt


def _proof_report_file_receipt(
    report: dict[str, Any],
    report_path: Path | None = None,
    *,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_path = report_path
    if selected_path is None:
        raw_path = str(report.get("reportPath") or "").strip()
        selected_path = Path(raw_path) if raw_path else None
    return _local_evidence_receipt(
        selected_path,
        schema=PROOF_EVIDENCE_RECEIPT_SCHEMA,
        path_key="reportPath",
        missing_path_status="missing_report_path",
        missing_file_status="missing_report_file",
        source="local-verifier-report",
        receipt_cache=receipt_cache,
    )


def _proof_evidence_path(raw_path: object, report_path: Path | None = None) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute() and report_path is not None:
        path = report_path.parent / path
    return path


def _proof_evidence_path_from_root(raw_path: object, root: Path) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root / path


def _proof_screenshot_label(key: str, value: object = "") -> str:
    explicit = str(value or "").strip()
    if explicit:
        return explicit
    return re.sub(r"(?<!^)([A-Z])", r" \1", key).replace("_", " ").replace("-", " ").strip().title()


def _proof_screenshot_requirement_id(receipt: dict[str, Any]) -> str:
    key = str(receipt.get("screenshotKey") or "").strip()
    normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
    label = str(receipt.get("label") or "").strip().lower()
    for requirement in PROOF_SCREENSHOT_REQUIREMENTS:
        aliases = requirement.get("aliases")
        alias_set = aliases if isinstance(aliases, set) else set()
        normalized_aliases = {
            re.sub(r"[^a-z0-9]", "", str(alias).lower())
            for alias in alias_set
        }
        if normalized_key and normalized_key in normalized_aliases:
            return str(requirement["key"])
    if "agent" in label and ("ui" in label or "conversation" in label):
        return "agent_ui_screenshot"
    if "preview" in label or "produced output" in label:
        return "produced_output_preview"
    return ""


def _proof_screenshot_file_receipt(
    raw_path: object,
    *,
    screenshot_key: str,
    label: str = "",
    report_path: Path | None = None,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_path = _proof_evidence_path(raw_path, report_path)
    return _local_evidence_receipt(
        selected_path,
        schema=PROOF_SCREENSHOT_RECEIPT_SCHEMA,
        path_key="screenshotPath",
        missing_path_status="missing_screenshot_path",
        missing_file_status="missing_screenshot_file",
        source="local-verifier-screenshot",
        extra={
            "evidenceKind": "screenshot",
            "screenshotKey": screenshot_key,
            "label": _proof_screenshot_label(screenshot_key, label),
        },
        receipt_cache=receipt_cache,
    )


def _proof_screenshot_receipts(
    report: dict[str, Any],
    report_path: Path | None = None,
    *,
    receipt_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_receipt(screenshot_key: str, raw_path: object, *, label: object = "") -> None:
        receipt = _proof_screenshot_file_receipt(
            raw_path,
            screenshot_key=screenshot_key,
            label=str(label or ""),
            report_path=report_path,
            receipt_cache=receipt_cache,
        )
        dedupe_key = str(receipt.get("screenshotPath") or "").strip().lower()
        if dedupe_key and dedupe_key in seen_paths:
            return
        if dedupe_key:
            seen_paths.add(dedupe_key)
        receipts.append(receipt)

    screenshots = report.get("screenshots") if isinstance(report.get("screenshots"), dict) else {}
    for key, raw_path in screenshots.items():
        add_receipt(str(key), raw_path)

    bags = report.get("proofBags") if isinstance(report.get("proofBags"), dict) else {}
    for bag_id in ("agent_ui_screenshot", "produced_output_preview"):
        bag = bags.get(bag_id) if isinstance(bags, dict) else {}
        if not isinstance(bag, dict) or "screenshot" not in bag:
            continue
        add_receipt(str(bag_id), bag.get("screenshot"), label=bag.get("label"))
    return receipts


def _report_mission_id(report: dict[str, Any]) -> str:
    mission = report.get("mission") if isinstance(report.get("mission"), dict) else {}
    mission_summary = (
        report.get("missionDetailSummary")
        if isinstance(report.get("missionDetailSummary"), dict)
        else {}
    )
    for source in (mission, mission_summary, report):
        for key in ("missionId", "mission_id", "id"):
            value = str(source.get(key) or "").strip() if isinstance(source, dict) else ""
            if value:
                return value
    return ""


def _safe_mission_artifact_id(value: str) -> str:
    mission_id = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+", mission_id):
        return mission_id
    return ""


def _same_filesystem_path(left: object, right: object) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    try:
        return Path(left_text).resolve() == Path(right_text).resolve()
    except OSError:
        return left_text.replace("\\", "/").lower() == right_text.replace("\\", "/").lower()


def _preview_bridge_screenshot_requirement_key(raw_key: object) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", str(raw_key or "").lower())
    if normalized in {"agentconversation", "agentuiscreenshot"}:
        return "agent_ui_screenshot"
    if normalized in {
        "producedoutputpreview",
        "agentpreviewafterclick",
        "previewafterclick",
        "agentpreviewwindow",
    }:
        return "produced_output_preview"
    return ""


def _preview_bridge_screenshot_receipt(
    raw_path: object,
    *,
    screenshot_key: str,
    original_screenshot_key: str,
    proof: dict[str, Any],
    proof_path: Path,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_path = _proof_evidence_path(raw_path, proof_path)
    label = next(
        (
            str(item["label"])
            for item in PROOF_SCREENSHOT_REQUIREMENTS
            if str(item["key"]) == screenshot_key
        ),
        _proof_screenshot_label(screenshot_key),
    )
    return _local_evidence_receipt(
        selected_path,
        schema=PROOF_SCREENSHOT_RECEIPT_SCHEMA,
        path_key="screenshotPath",
        missing_path_status="missing_screenshot_path",
        missing_file_status="missing_screenshot_file",
        source="preview-bridge-proof",
        extra={
            "evidenceKind": "screenshot",
            "screenshotKey": screenshot_key,
            "originalScreenshotKey": original_screenshot_key,
            "label": label,
            "bridgeProofPath": str(proof_path),
            "bridgeProofStatus": str(proof.get("status") or ""),
            "bridgeProofCheckedAt": str(proof.get("checkedAt") or ""),
            "missionId": str(proof.get("missionId") or ""),
        },
        receipt_cache=receipt_cache,
    )


def _preview_bridge_screenshot_receipts(
    root: Path,
    report: dict[str, Any],
    *,
    report_path: Path | None = None,
    receipt_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    mission_id = _safe_mission_artifact_id(_report_mission_id(report))
    if not mission_id:
        return []
    proof_dir = Path(root).resolve() / ".agent_control" / "mission_artifacts" / mission_id / "preview_bridge_proof"
    if not proof_dir.exists():
        return []

    bridge_proofs: list[tuple[dict[str, Any], Path]] = []
    for proof_path in proof_dir.glob("*_preview_bridge_proof.json"):
        proof = _read_json(proof_path)
        if proof.get("schema") != "fluxio.preview_bridge_proof.v1":
            continue
        if str(proof.get("missionId") or "").strip() != mission_id:
            continue
        bridge_report_path = str(proof.get("reportPath") or "").strip()
        if bridge_report_path and report_path is not None and not _same_filesystem_path(bridge_report_path, report_path):
            continue
        bridge_proofs.append((proof, proof_path))

    bridge_proofs.sort(key=lambda item: _created_sort_key(item[0], item[1]), reverse=True)
    receipts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for proof, proof_path in bridge_proofs:
        screenshots = proof.get("screenshots") if isinstance(proof.get("screenshots"), dict) else {}
        for raw_key, raw_path in screenshots.items():
            requirement_key = _preview_bridge_screenshot_requirement_key(raw_key)
            if not requirement_key:
                continue
            receipt = _preview_bridge_screenshot_receipt(
                raw_path,
                screenshot_key=requirement_key,
                original_screenshot_key=str(raw_key),
                proof=proof,
                proof_path=proof_path,
                receipt_cache=receipt_cache,
            )
            dedupe_key = (
                requirement_key,
                str(receipt.get("screenshotPath") or "").strip().lower(),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            receipts.append(receipt)
    return receipts


def _authenticated_live_agent_report_candidates(root: Path) -> list[Path]:
    root = Path(root).resolve()
    candidates: list[Path] = []
    candidates.extend((root / "tmp-ui-checks" / "authenticated-live-agent").glob("*-check.json"))
    candidates.extend((root / ".agent_control").glob("*live-agent*check.json"))
    candidates.extend((root / ".agent_control" / "screenshots").glob("*live-agent*check.json"))
    candidates.extend((root / ".agent_control" / "release_artifacts").glob("*/authenticated_live_agent/*-check.json"))
    seen: set[str] = set()
    deduped: list[Path] = []
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key in seen or not candidate.exists():
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _authenticated_live_agent_report_index(root: Path) -> dict[str, list[tuple[dict[str, Any], Path]]]:
    indexed: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    for proof_path in _authenticated_live_agent_report_candidates(root):
        agent_report = _read_json(proof_path)
        if agent_report.get("schema") != "fluxio.authenticated_live_agent.v1":
            continue
        mission_id = _authenticated_live_agent_selected_mission_id(agent_report)
        if not mission_id:
            continue
        if not _authenticated_live_agent_check_passed(agent_report, "not-login-screen"):
            continue
        if not _authenticated_live_agent_check_passed(agent_report, "selected-mission-visible-in-agent"):
            continue
        if not _authenticated_live_agent_check_passed(agent_report, "screenshot-nonblank"):
            continue
        indexed.setdefault(mission_id, []).append((agent_report, proof_path))
    for rows in indexed.values():
        rows.sort(key=lambda item: _created_sort_key(item[0], item[1]), reverse=True)
    return indexed


def _authenticated_live_agent_selected_mission_id(report: dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    selected = summary.get("selectedMission") if isinstance(summary.get("selectedMission"), dict) else {}
    for source in (selected, report):
        for key in ("mission_id", "missionId", "id"):
            value = str(source.get(key) or "").strip() if isinstance(source, dict) else ""
            if value:
                return value
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    for check_id in ("selected-live-mission", "selected-mission-detail-api", "selected-mission-visible-in-agent"):
        for check in checks:
            if not isinstance(check, dict) or check.get("checkId") != check_id:
                continue
            value = str(check.get("missionId") or "").strip()
            if value:
                return value
    return ""


def _authenticated_live_agent_check_passed(report: dict[str, Any], check_id: str) -> bool:
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    return any(
        isinstance(item, dict)
        and str(item.get("checkId") or "") == check_id
        and bool(item.get("passed"))
        for item in checks
    )


def _authenticated_live_agent_screenshot_receipt(
    raw_path: object,
    *,
    root: Path,
    report: dict[str, Any],
    proof_path: Path,
    mission_id: str,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_path = _proof_evidence_path(raw_path, proof_path)
    if selected_path is not None and not selected_path.exists():
        root_path = _proof_evidence_path_from_root(raw_path, root)
        if root_path is not None and root_path.exists():
            selected_path = root_path
    return _local_evidence_receipt(
        selected_path,
        schema=PROOF_SCREENSHOT_RECEIPT_SCHEMA,
        path_key="screenshotPath",
        missing_path_status="missing_screenshot_path",
        missing_file_status="missing_screenshot_file",
        source="authenticated-live-agent",
        extra={
            "evidenceKind": "screenshot",
            "screenshotKey": "agent_ui_screenshot",
            "label": "Agent UI screenshot",
            "authenticatedAgentReportPath": str(proof_path),
            "authenticatedAgentCheckedAt": str(report.get("checkedAt") or ""),
            "authenticatedAgentOk": bool(report.get("ok")),
            "missionId": mission_id,
            "agentUrl": str(report.get("url") or ""),
        },
        receipt_cache=receipt_cache,
    )


def _authenticated_live_agent_screenshot_receipts(
    root: Path,
    report: dict[str, Any],
    *,
    receipt_cache: dict[str, Any] | None = None,
    agent_report_index: dict[str, list[tuple[dict[str, Any], Path]]] | None = None,
) -> list[dict[str, Any]]:
    mission_id = _safe_mission_artifact_id(_report_mission_id(report))
    if not mission_id:
        return []
    if isinstance(agent_report_index, dict):
        matched_reports = agent_report_index.get(mission_id) or []
    else:
        matched_reports = []
        for proof_path in _authenticated_live_agent_report_candidates(root):
            agent_report = _read_json(proof_path)
            if agent_report.get("schema") != "fluxio.authenticated_live_agent.v1":
                continue
            if _authenticated_live_agent_selected_mission_id(agent_report) != mission_id:
                continue
            if not _authenticated_live_agent_check_passed(agent_report, "not-login-screen"):
                continue
            if not _authenticated_live_agent_check_passed(agent_report, "selected-mission-visible-in-agent"):
                continue
            if not _authenticated_live_agent_check_passed(agent_report, "screenshot-nonblank"):
                continue
            matched_reports.append((agent_report, proof_path))
        matched_reports.sort(key=lambda item: _created_sort_key(item[0], item[1]), reverse=True)
    receipts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for agent_report, proof_path in matched_reports:
        artifacts = agent_report.get("artifacts") if isinstance(agent_report.get("artifacts"), dict) else {}
        screenshot_path = str(artifacts.get("screenshotPath") or "").strip()
        if not screenshot_path:
            continue
        receipt = _authenticated_live_agent_screenshot_receipt(
            screenshot_path,
            root=root,
            report=agent_report,
            proof_path=proof_path,
            mission_id=mission_id,
            receipt_cache=receipt_cache,
        )
        dedupe_key = str(receipt.get("screenshotPath") or "").strip().lower()
        if dedupe_key in seen_paths:
            continue
        if dedupe_key:
            seen_paths.add(dedupe_key)
        receipts.append(receipt)
    return receipts


def _reconciled_screenshot_receipts(
    root: Path,
    report: dict[str, Any],
    *,
    report_path: Path | None = None,
    receipt_cache: dict[str, Any] | None = None,
    agent_report_index: dict[str, list[tuple[dict[str, Any], Path]]] | None = None,
) -> list[dict[str, Any]]:
    return _merge_screenshot_receipts(
        _authenticated_live_agent_screenshot_receipts(
            root,
            report,
            receipt_cache=receipt_cache,
            agent_report_index=agent_report_index,
        ),
        _preview_bridge_screenshot_receipts(root, report, report_path=report_path, receipt_cache=receipt_cache),
    )


def _merge_screenshot_receipts(*receipt_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for group in receipt_groups:
        for receipt in group:
            if not isinstance(receipt, dict):
                continue
            path = str(receipt.get("screenshotPath") or "").strip().lower()
            if path and path in seen_paths:
                continue
            if path:
                seen_paths.add(path)
            merged.append(receipt)
    return merged


def _merge_evidence_receipts(*receipt_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for group in receipt_groups:
        for receipt in group:
            if not isinstance(receipt, dict):
                continue
            path = str(receipt.get("reportPath") or "").strip().lower()
            if path and path in seen_paths:
                continue
            if path:
                seen_paths.add(path)
            merged.append(receipt)
    return merged


def _proof_evidence_health(
    proof_evidence_receipts: list[dict[str, Any]],
    proof_screenshot_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    report_receipts = [item for item in proof_evidence_receipts if isinstance(item, dict)]
    screenshot_receipts = [item for item in proof_screenshot_receipts if isinstance(item, dict)]
    attached_reports = [
        item
        for item in report_receipts
        if item.get("exists") and str(item.get("sha256") or "").strip()
    ]
    missing_reports = [item for item in report_receipts if not item.get("exists")]
    attached_screenshots = [
        item
        for item in screenshot_receipts
        if item.get("exists") and str(item.get("sha256") or "").strip()
    ]
    missing_screenshots = [item for item in screenshot_receipts if not item.get("exists")]
    required_screenshot_keys = [str(item["key"]) for item in PROOF_SCREENSHOT_REQUIREMENTS]
    attached_required_screenshot_keys = [
        str(item["key"])
        for item in PROOF_SCREENSHOT_REQUIREMENTS
        if any(_proof_screenshot_requirement_id(receipt) == item["key"] for receipt in attached_screenshots)
    ]
    missing_required_screenshots = [
        item
        for item in PROOF_SCREENSHOT_REQUIREMENTS
        if str(item["key"]) not in attached_required_screenshot_keys
    ]
    missing_required_screenshot_keys = [str(item["key"]) for item in missing_required_screenshots]
    missing_required_screenshot_labels = [str(item["label"]) for item in missing_required_screenshots]

    if not report_receipts:
        status = "missing_report"
        next_action = "Run the real-agent verifier so Neyvia can attach a JSON proof report."
    elif not attached_reports:
        status = "missing_report_file"
        next_action = "Restore the verifier JSON report file or rerun the real-agent verifier."
    elif missing_screenshots:
        status = "missing_screenshot"
        next_action = "Rerun with browser capture or restore the referenced Agent and Preview screenshots."
    elif attached_screenshots and missing_required_screenshot_keys:
        status = "partial_screenshot"
        next_action = (
            "Capture the missing real-agent proof screenshot(s): "
            + ", ".join(missing_required_screenshot_labels)
            + "."
        )
    elif attached_screenshots:
        status = "complete"
        next_action = "JSON report and screenshot evidence files are attached."
    else:
        status = "report_only"
        next_action = "Run with browser capture to attach Agent and Preview screenshots."

    return {
        "schema": PROOF_EVIDENCE_HEALTH_SCHEMA,
        "status": status,
        "reportReceiptCount": len(report_receipts),
        "reportAttachedCount": len(attached_reports),
        "missingReportReceiptCount": len(missing_reports),
        "screenshotReceiptCount": len(screenshot_receipts),
        "screenshotAttachedCount": len(attached_screenshots),
        "missingScreenshotReceiptCount": len(missing_screenshots),
        "requiredScreenshotKeys": required_screenshot_keys,
        "attachedRequiredScreenshotKeys": attached_required_screenshot_keys,
        "missingRequiredScreenshotKeys": missing_required_screenshot_keys,
        "missingRequiredScreenshotLabels": missing_required_screenshot_labels,
        "missingRequiredScreenshotCount": len(missing_required_screenshot_keys),
        "hasUsableReport": bool(attached_reports),
        "hasUsableScreenshots": bool(attached_screenshots)
        and not missing_screenshots
        and not missing_required_screenshot_keys,
        "allEvidenceAttached": status == "complete",
        "nextEvidenceAction": next_action,
    }


def _attached_receipt(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    for receipt in receipts:
        if (
            isinstance(receipt, dict)
            and receipt.get("exists")
            and str(receipt.get("sha256") or "").strip()
        ):
            return receipt
    return receipts[0] if receipts else {}


def _checklist_receipt_fields(receipt: dict[str, Any], path_key: str) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return {}
    fields: dict[str, Any] = {}
    for key in (
        path_key,
        "sha256",
        "sizeBytes",
        "modifiedAt",
        "source",
        "originalScreenshotKey",
        "bridgeProofPath",
        "bridgeProofStatus",
        "bridgeProofCheckedAt",
        "authenticatedAgentReportPath",
        "authenticatedAgentCheckedAt",
        "authenticatedAgentOk",
        "agentUrl",
        "missionId",
    ):
        value = receipt.get(key)
        if value not in (None, ""):
            fields[key] = value
    return fields


def _proof_evidence_checklist(
    proof_evidence_receipts: list[dict[str, Any]],
    proof_screenshot_receipts: list[dict[str, Any]],
    *,
    evidence_health: dict[str, Any] | None = None,
    stale: bool = False,
) -> dict[str, Any]:
    health = (
        evidence_health
        if isinstance(evidence_health, dict)
        else _proof_evidence_health(proof_evidence_receipts, proof_screenshot_receipts)
    )
    report_receipts = [item for item in proof_evidence_receipts if isinstance(item, dict)]
    screenshot_receipts = [item for item in proof_screenshot_receipts if isinstance(item, dict)]
    items: list[dict[str, Any]] = []

    report_receipt = _attached_receipt(report_receipts)
    report_attached = bool(report_receipt.get("exists") and report_receipt.get("sha256"))
    report_status = "attached" if report_attached else str(
        report_receipt.get("status") or health.get("status") or "missing_report"
    )
    items.append(
        {
            "id": "verifier_report",
            "label": "Verifier JSON report",
            "kind": "report",
            "required": True,
            "status": report_status,
            "passed": report_attached,
            "nextAction": "Verifier report is attached."
            if report_attached
            else "Run the real-agent verifier so Neyvia can attach a JSON proof report.",
            **_checklist_receipt_fields(report_receipt, "reportPath"),
        }
    )

    for requirement in PROOF_SCREENSHOT_REQUIREMENTS:
        requirement_id = str(requirement["key"])
        matching_receipts = [
            receipt
            for receipt in screenshot_receipts
            if _proof_screenshot_requirement_id(receipt) == requirement_id
        ]
        receipt = _attached_receipt(matching_receipts)
        attached = bool(receipt.get("exists") and receipt.get("sha256"))
        status = "attached" if attached else "missing_required_screenshot"
        if matching_receipts and not attached:
            status = str(receipt.get("status") or "missing_screenshot")
        label = str(requirement["label"])
        items.append(
            {
                "id": requirement_id,
                "label": label,
                "kind": "screenshot",
                "required": True,
                "status": status,
                "passed": attached,
                "nextAction": f"{label} is attached."
                if attached
                else f"Capture the missing real-agent proof screenshot: {label}.",
                **_checklist_receipt_fields(receipt, "screenshotPath"),
            }
        )

    missing_items = [item for item in items if item["required"] and not item["passed"]]
    attached_count = len([item for item in items if item["passed"]])
    return {
        "schema": PROOF_EVIDENCE_CHECKLIST_SCHEMA,
        "status": health.get("status") or "unknown",
        "total": len(items),
        "requiredCount": len([item for item in items if item["required"]]),
        "attachedCount": attached_count,
        "missingCount": len(missing_items),
        "allRequiredAttached": not missing_items,
        "stale": bool(stale),
        "items": items,
        "nextMissing": missing_items[0] if missing_items else {},
        "nextAction": (
            "JSON report and required screenshots are attached."
            if not missing_items
            else missing_items[0]["nextAction"]
        ),
        "source": "real-agent-proof-evidence-receipts",
    }


def _capture_source_label(source: str, capture_labels: list[str]) -> str:
    if capture_labels:
        return capture_labels[0]
    if not source or source == "missing":
        return "No transcript source"
    return source.replace("-", " ").strip().title()


def _summary_line(parts: list[object]) -> str:
    return "; ".join(str(item).strip() for item in parts if str(item or "").strip())


def _dialogue_turn_label(count: int) -> str:
    return f"{count} dialogue turn" if count == 1 else f"{count} dialogue turns"


def _proof_runtime_label(runtime: str) -> str:
    runtime_id = str(runtime or "").strip().lower()
    if runtime_id == "openclaw":
        return "OpenClaw"
    if runtime_id == "hermes":
        return "Hermes"
    if runtime_id == "mixed":
        return "Mixed Hermes/OpenClaw"
    return runtime_id.title() if runtime_id else "Runtime"


def _runtime_summary_receipt(summary: dict[str, Any]) -> dict[str, Any]:
    receipt = summary.get("proofTranscriptReceipt") if isinstance(summary.get("proofTranscriptReceipt"), dict) else {}
    return receipt if isinstance(receipt, dict) else {}


def _runtime_summary_has_real_transcript(summary: dict[str, Any]) -> bool:
    receipt = _runtime_summary_receipt(summary)
    return (
        bool(summary.get("realRuntimeOutput"))
        or bool(receipt.get("hasRealTranscript"))
        or bool(receipt.get("realRuntimeOutput"))
    )


def _runtime_summary_has_fresh_transcript(summary: dict[str, Any]) -> bool:
    receipt = _runtime_summary_receipt(summary)
    return (
        bool(summary.get("freshRuntimeOutput"))
        or bool(receipt.get("freshRuntimeOutput"))
        or str(receipt.get("status") or "").strip().lower() == "fresh"
    )


def _mixed_runtime_transcript_coverage(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        str(item.get("runtime") or "").strip().lower(): item
        for item in runs
        if isinstance(item, dict) and str(item.get("runtime") or "").strip().lower()
    }
    rows: list[dict[str, Any]] = []
    for runtime in MIXED_REQUIRED_RUNTIME_IDS:
        summary = by_runtime.get(runtime, {})
        receipt = _runtime_summary_receipt(summary)
        fresh = _runtime_summary_has_fresh_transcript(summary)
        real = _runtime_summary_has_real_transcript(summary)
        status = str(summary.get("status") or receipt.get("status") or "missing").strip().lower() or "missing"
        transcript_status = str(receipt.get("status") or ("fresh" if fresh else "stored" if real else status)).strip().lower() or "missing"
        blocker = _compact_problem_text(
            summary.get("blocker")
            or receipt.get("blocker")
            or summary.get("nextAction")
            or ""
        )
        blocked = (
            status == "blocked"
            or transcript_status == "blocked"
            or bool(receipt.get("hasStoredBlocker"))
            or bool(blocker and not real)
        )
        rows.append(
            {
                "runtime": runtime,
                "label": _proof_runtime_label(runtime),
                "status": status,
                "transcriptStatus": transcript_status,
                "freshRuntimeOutput": fresh,
                "realRuntimeOutput": real,
                "blocker": blocker,
                "blocked": blocked,
                "source": str(receipt.get("source") or summary.get("transcriptSource") or ""),
                "summaryLine": str(receipt.get("summaryLine") or summary.get("transcriptSummaryLine") or ""),
            }
        )

    real_runtime_ids = [row["runtime"] for row in rows if row["realRuntimeOutput"]]
    fresh_runtime_ids = [row["runtime"] for row in rows if row["freshRuntimeOutput"]]
    blocked_runtime_ids = [row["runtime"] for row in rows if row["blocked"] and not row["realRuntimeOutput"]]
    missing_runtime_ids = [
        row["runtime"]
        for row in rows
        if not row["realRuntimeOutput"] and row["runtime"] not in blocked_runtime_ids
    ]
    required_count = len(MIXED_REQUIRED_RUNTIME_IDS)
    real_count = len(real_runtime_ids)
    fresh_count = len(fresh_runtime_ids)
    summary_parts = [
        f"{real_count}/{required_count} runtime transcripts real",
        f"{fresh_count}/{required_count} fresh",
    ]
    if blocked_runtime_ids:
        summary_parts.append("blocked: " + ", ".join(_proof_runtime_label(item) for item in blocked_runtime_ids))
    if missing_runtime_ids:
        summary_parts.append("missing: " + ", ".join(_proof_runtime_label(item) for item in missing_runtime_ids))
    return {
        "requiredRuntimeIds": list(MIXED_REQUIRED_RUNTIME_IDS),
        "requiredRuntimeCount": required_count,
        "rows": rows,
        "realRuntimeIds": real_runtime_ids,
        "freshRuntimeIds": fresh_runtime_ids,
        "blockedRuntimeIds": blocked_runtime_ids,
        "missingRuntimeIds": missing_runtime_ids,
        "realRuntimeCount": real_count,
        "freshRuntimeCount": fresh_count,
        "blockedRuntimeCount": len(blocked_runtime_ids),
        "missingRuntimeCount": len(missing_runtime_ids),
        "anyRuntimeTranscriptOutput": bool(real_runtime_ids),
        "allRuntimeTranscriptsReal": real_count == required_count,
        "allRuntimeTranscriptsFresh": fresh_count == required_count,
        "summaryLine": _summary_line(summary_parts),
    }


def _empty_transcript_receipt(runtime: str = "") -> dict[str, Any]:
    return {
        "schema": PROOF_TRANSCRIPT_RECEIPT_SCHEMA,
        "runtime": str(runtime or ""),
        "status": "missing",
        "source": "missing",
        "sourceLabel": "No transcript source",
        "captureModes": [],
        "captureLabels": [],
        "dialogueCount": 0,
        "artifactGatePassed": False,
        "freshRuntimeOutput": False,
        "recoveredRuntimeOutput": False,
        "realRuntimeOutput": False,
        "hasRealTranscript": False,
        "hasStoredDialogue": False,
        "hasStoredBlocker": False,
        "runtimeSessionId": "",
        "recoveredSessionId": "",
        "sourcePath": "",
        "reportPath": "",
        "runtimeCoverage": {},
        "summaryLine": "No real runtime transcript has been recorded.",
        "blocker": "",
        "sourceDetail": "",
        "receiptSource": "real-agent-proof-status",
    }


def _runtime_transcript_receipt(
    report: dict[str, Any],
    *,
    runtime: str,
    fresh_bag: dict[str, Any],
    recovered_bag: dict[str, Any],
    mission_summary: dict[str, Any],
    latest_attempt: dict[str, Any],
    blocker: str,
    report_path: Path | None,
) -> dict[str, Any]:
    raw_capture_modes = mission_summary.get("dialogueCaptureModes")
    raw_capture_labels = mission_summary.get("dialogueCaptureLabels")
    capture_modes = [
        str(item).strip()
        for item in (raw_capture_modes if isinstance(raw_capture_modes, list) else [])
        if str(item or "").strip()
    ]
    capture_labels = [
        str(item).strip()
        for item in (raw_capture_labels if isinstance(raw_capture_labels, list) else [])
        if str(item or "").strip()
    ]
    fresh_status = str(fresh_bag.get("status") or "").lower()
    recovered_status = str(recovered_bag.get("status") or "").lower()
    try:
        dialogue_count = max(0, int(mission_summary.get("dialogueCount") or 0))
    except (TypeError, ValueError):
        dialogue_count = 0
    fresh_runtime_output = fresh_status == "collected"
    recovered_runtime_output = runtime == "openclaw" and recovered_status == "collected" and not fresh_runtime_output
    real_runtime_output = fresh_runtime_output or recovered_runtime_output or dialogue_count > 0
    blocker_text = _compact_problem_text(blocker or report.get("nextAction") or "")
    recovered_reply = report.get("recoveredRuntimeReply") if isinstance(report.get("recoveredRuntimeReply"), dict) else {}
    attempt_recovered = (
        latest_attempt.get("recoveredRuntimeReply")
        if isinstance(latest_attempt.get("recoveredRuntimeReply"), dict)
        else {}
    )

    if fresh_runtime_output:
        status = "fresh"
        source = capture_modes[0] if capture_modes else "fresh-runtime-command"
    elif recovered_runtime_output:
        status = "recovered"
        source = capture_modes[0] if capture_modes else "recovered-persisted-session"
    elif dialogue_count > 0:
        status = "stored"
        source = capture_modes[0] if capture_modes else "stored-mission-dialogue"
    elif blocker_text:
        status = "blocked"
        source = "stored-runtime-blocker"
    else:
        status = "missing"
        source = "missing"

    source_label = _capture_source_label(source, capture_labels)
    source_path = (
        recovered_bag.get("sourcePath")
        or recovered_reply.get("sourcePath")
        or attempt_recovered.get("sourcePath")
        or latest_attempt.get("recoveredFrom")
        or ""
    )
    recovered_session_id = (
        recovered_reply.get("sessionId")
        or attempt_recovered.get("sessionId")
        or latest_attempt.get("recoveredSessionId")
        or ""
    )
    runtime_session_id = (
        report.get("runtimeSessionId")
        or recovered_session_id
        or latest_attempt.get("runtimeSessionId")
        or ""
    )
    summary_parts: list[object] = [source_label]
    if dialogue_count:
        summary_parts.append(_dialogue_turn_label(dialogue_count))
    if bool(mission_summary.get("artifactGatePassed")):
        summary_parts.append("artifact gate passed")
    if status == "blocked" and blocker_text:
        summary_parts.append(blocker_text)

    return {
        "schema": PROOF_TRANSCRIPT_RECEIPT_SCHEMA,
        "runtime": runtime,
        "status": status,
        "source": source,
        "sourceLabel": source_label,
        "captureModes": capture_modes,
        "captureLabels": capture_labels,
        "dialogueCount": dialogue_count,
        "artifactGatePassed": bool(mission_summary.get("artifactGatePassed")),
        "freshRuntimeOutput": fresh_runtime_output,
        "recoveredRuntimeOutput": recovered_runtime_output,
        "realRuntimeOutput": real_runtime_output,
        "hasRealTranscript": real_runtime_output,
        "hasStoredDialogue": dialogue_count > 0,
        "hasStoredBlocker": status == "blocked",
        "runtimeSessionId": str(runtime_session_id or ""),
        "recoveredSessionId": str(recovered_session_id or ""),
        "sourcePath": _compact_problem_text(source_path, 320),
        "reportPath": str(report_path or report.get("reportPath") or ""),
        "summaryLine": _summary_line(summary_parts),
        "blocker": blocker_text if status == "blocked" else "",
        "sourceDetail": (
            "Fresh runtime output reached the mission transcript."
            if status == "fresh"
            else "Persisted OpenClaw output was recovered and reached the mission transcript."
            if status == "recovered"
            else "Mission storage contains runtime dialogue, but the verifier report predates source receipts."
            if status == "stored"
            else "The verifier stored an explicit runtime blocker instead of a transcript."
            if status == "blocked"
            else "No runtime transcript source is available yet."
        ),
        "receiptSource": "real-agent-proof-status",
    }


def _proof_transcript_health(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    transcript_receipts = [item for item in receipts if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    for receipt in transcript_receipts:
        status = str(receipt.get("status") or "missing").strip().lower() or "missing"
        status_counts[status] = status_counts.get(status, 0) + 1

    non_missing_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "missing").strip().lower() != "missing"
    ]
    fresh_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "").strip().lower() == "fresh"
        or bool(receipt.get("freshRuntimeOutput"))
    ]
    recovered_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "").strip().lower() == "recovered"
        or bool(receipt.get("recoveredRuntimeOutput"))
    ]
    stored_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "").strip().lower() == "stored"
    ]
    partial_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "").strip().lower() == "partial"
    ]
    blocked_receipts = [
        receipt
        for receipt in transcript_receipts
        if str(receipt.get("status") or "").strip().lower() == "blocked"
        or bool(receipt.get("hasStoredBlocker"))
    ]
    real_receipts = [
        receipt
        for receipt in transcript_receipts
        if bool(receipt.get("hasRealTranscript")) or bool(receipt.get("realRuntimeOutput"))
    ]

    latest_receipt = non_missing_receipts[0] if non_missing_receipts else {}
    if fresh_receipts:
        status = "fresh"
        next_action = "Fresh real runtime transcript proof is attached."
    elif recovered_receipts:
        status = "recovered"
        next_action = "Rerun the real-agent proof to replace recovered transcript proof with fresh runtime output."
    elif stored_receipts:
        status = "stored"
        next_action = "Rerun the verifier so stored mission dialogue gets fresh runtime-source receipts."
    elif partial_receipts or real_receipts:
        status = "partial"
        next_action = "Rerun mixed real-agent proof until every runtime has fresh transcript output."
    elif blocked_receipts:
        status = "blocked"
        blocked_detail = _compact_problem_text(blocked_receipts[0].get("blocker") or blocked_receipts[0].get("summaryLine"))
        next_action = blocked_detail or "Fix the runtime blocker, then rerun the real-agent verifier."
    else:
        status = "missing"
        next_action = "Run the real-agent verifier so Neyvia can record a real runtime transcript."

    return {
        "schema": PROOF_TRANSCRIPT_HEALTH_SCHEMA,
        "status": status,
        "receiptCount": len(transcript_receipts),
        "nonMissingReceiptCount": len(non_missing_receipts),
        "freshCount": len(fresh_receipts),
        "recoveredCount": len(recovered_receipts),
        "storedCount": len(stored_receipts),
        "partialCount": len(partial_receipts),
        "blockedCount": len(blocked_receipts),
        "missingCount": status_counts.get("missing", 0),
        "realTranscriptCount": len(real_receipts),
        "hasRealTranscript": bool(real_receipts),
        "hasFreshTranscript": bool(fresh_receipts),
        "hasRecoveredTranscript": bool(recovered_receipts),
        "needsFreshTranscript": status in {"recovered", "stored", "partial", "blocked", "missing"},
        "latestRuntime": str(latest_receipt.get("runtime") or ""),
        "latestSource": str(latest_receipt.get("source") or "missing"),
        "latestSummaryLine": str(latest_receipt.get("summaryLine") or ""),
        "latestReceipt": latest_receipt,
        "statusCounts": status_counts,
        "nextTranscriptAction": next_action,
        "source": "real-agent-proof-transcript-receipts",
    }


def _proof_bag(report: dict[str, Any], bag_id: str) -> dict[str, Any]:
    bags = report.get("proofBags") if isinstance(report.get("proofBags"), dict) else {}
    bag = bags.get(bag_id) if isinstance(bags, dict) else {}
    return bag if isinstance(bag, dict) else {}


def _proof_bag_label(bag_id: str, bag: dict[str, Any]) -> str:
    label = str(bag.get("label") or "").strip()
    if label:
        return label
    return bag_id.replace("_", " ").strip().title() or "Proof bag"


def _normalized_proof_bag_status(value: object) -> str:
    status = str(value or "missing").strip().lower()
    if not status:
        return "missing"
    return status


def _empty_proof_bag_summary() -> dict[str, Any]:
    return {
        "schema": "fluxio.real_agent_proof_bag_status.v1",
        "total": 0,
        "counts": {},
        "collectedCount": 0,
        "blockedCount": 0,
        "missingCount": 0,
        "skippedCount": 0,
        "incompleteCount": 0,
        "openCount": 0,
        "allCollected": False,
        "allClosed": False,
        "rows": [],
        "blocked": [],
        "missingOrSkipped": [],
        "nextBag": {},
        "nextAction": "",
        "source": "no-proof-bags",
    }


def _evidence_target_label(evidence_health: dict[str, Any]) -> str:
    status = str(evidence_health.get("status") or "").strip()
    labels = [
        str(item)
        for item in evidence_health.get("missingRequiredScreenshotLabels", [])
        if str(item or "").strip()
    ]
    if status == "missing_report":
        return "Verifier report"
    if status == "missing_report_file":
        return "Verifier report file"
    if labels:
        return ", ".join(labels)
    if status == "missing_screenshot":
        return "Referenced proof screenshot"
    if status in {"partial_screenshot", "report_only"}:
        return "Agent and Preview screenshots"
    return ""


def _proof_next_target(summary: dict[str, Any]) -> dict[str, Any]:
    runtime = str(summary.get("runtime") or "").strip()
    report_path = str(summary.get("reportPath") or "").strip()
    evidence_health = (
        summary.get("proofEvidenceHealth")
        if isinstance(summary.get("proofEvidenceHealth"), dict)
        else {}
    )
    proof_bag_summary = (
        summary.get("proofBagSummary")
        if isinstance(summary.get("proofBagSummary"), dict)
        else {}
    )
    next_bag = (
        proof_bag_summary.get("nextBag")
        if isinstance(proof_bag_summary.get("nextBag"), dict)
        else {}
    )
    next_action = _compact_problem_text(
        proof_bag_summary.get("nextAction")
        or summary.get("nextProofAction")
        or summary.get("nextAction")
    )
    evidence_status = str(
        evidence_health.get("status") or summary.get("evidenceStatus") or ""
    ).strip()
    evidence_action = _compact_problem_text(
        evidence_health.get("nextEvidenceAction") or summary.get("nextEvidenceAction")
    )
    bag_status = str(next_bag.get("status") or "").strip()

    if next_bag and bag_status == "blocked":
        return {
            "schema": PROOF_NEXT_TARGET_SCHEMA,
            "kind": "proof_bag",
            "runtime": runtime,
            "status": bag_status,
            "label": str(next_bag.get("label") or ""),
            "bagId": str(next_bag.get("bagId") or ""),
            "detail": _compact_problem_text(next_bag.get("detail")),
            "evidenceStatus": evidence_status,
            "action": next_action or _compact_problem_text(next_bag.get("detail")),
            "reportPath": report_path,
            "source": "proof-bag-summary",
        }

    if evidence_status and evidence_status != "complete":
        return {
            "schema": PROOF_NEXT_TARGET_SCHEMA,
            "kind": "evidence",
            "runtime": runtime,
            "status": evidence_status,
            "label": _evidence_target_label(evidence_health),
            "bagId": "",
            "detail": evidence_action,
            "evidenceStatus": evidence_status,
            "action": evidence_action,
            "reportPath": report_path,
            "source": "proof-evidence-health",
        }

    if next_bag and bag_status:
        return {
            "schema": PROOF_NEXT_TARGET_SCHEMA,
            "kind": "proof_bag",
            "runtime": runtime,
            "status": bag_status,
            "label": str(next_bag.get("label") or ""),
            "bagId": str(next_bag.get("bagId") or ""),
            "detail": _compact_problem_text(next_bag.get("detail")),
            "evidenceStatus": evidence_status,
            "action": next_action or _compact_problem_text(next_bag.get("detail")),
            "reportPath": report_path,
            "source": "proof-bag-summary",
        }

    return {
        "schema": PROOF_NEXT_TARGET_SCHEMA,
        "kind": "none",
        "runtime": runtime,
        "status": "complete" if evidence_status == "complete" else "unknown",
        "label": "",
        "bagId": "",
        "detail": "",
        "evidenceStatus": evidence_status,
        "action": next_action or evidence_action,
        "reportPath": report_path,
        "source": "no-open-target",
    }


def _proof_command_runtime(summary: dict[str, Any], target: dict[str, Any]) -> str:
    runtime = str(summary.get("runtime") or target.get("runtime") or "").strip().lower()
    if runtime in SUPPORTED_PROOF_RUNTIMES:
        return runtime
    bag_id = str(target.get("bagId") or "").lower()
    label = str(target.get("label") or "").lower()
    if "openclaw" in bag_id or "openclaw" in label:
        return "openclaw"
    if "hermes" in bag_id or "hermes" in label:
        return "hermes"
    return "mixed"


def _proof_target_needs_browser(target: dict[str, Any]) -> bool:
    if str(target.get("kind") or "") == "evidence":
        return True
    text = " ".join(
        str(target.get(key) or "").lower()
        for key in ("status", "label", "detail", "action", "evidenceStatus")
    )
    return any(term in text for term in ("browser", "screenshot", "preview"))


def _proof_checklist_next_missing_id(summary: dict[str, Any]) -> str:
    checklist = (
        summary.get("proofEvidenceChecklist")
        if isinstance(summary.get("proofEvidenceChecklist"), dict)
        else {}
    )
    next_missing = (
        checklist.get("nextMissing")
        if isinstance(checklist.get("nextMissing"), dict)
        else {}
    )
    if next_missing:
        return str(next_missing.get("id") or "").strip()
    for item in checklist.get("items", []) if isinstance(checklist.get("items"), list) else []:
        if isinstance(item, dict) and item.get("required") and not item.get("passed"):
            return str(item.get("id") or "").strip()
    return ""


def _agent_ui_capture_name(runtime: str, mission_id: str) -> str:
    raw = f"real-agent-{runtime or 'runtime'}-agent-ui-{mission_id}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-")[:120] or "real-agent-agent-ui"


def _agent_ui_proof_capture_command(root: Path, summary: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    mission_id = _safe_mission_artifact_id(str(summary.get("missionId") or _report_mission_id(summary)))
    if not mission_id:
        return {}
    if _proof_checklist_next_missing_id(summary) != "agent_ui_screenshot":
        return {}
    runtime = str(summary.get("runtime") or target.get("runtime") or "agent-ui").strip().lower() or "agent-ui"
    out_dir = Path(root).resolve() / "tmp-ui-checks" / "authenticated-live-agent"
    name = _agent_ui_capture_name(runtime, mission_id)
    argv = [
        sys.executable,
        str(Path(root).resolve() / "scripts" / "verify_authenticated_live_agent.py"),
        "--mission-id",
        mission_id,
        "--out-dir",
        str(out_dir),
        "--name",
        name,
    ]
    return {
        "schema": PROOF_ACTION_COMMAND_SCHEMA,
        "available": True,
        "runtime": "agent-ui",
        "runtimeTimeout": 0,
        "withBrowser": True,
        "missionId": mission_id,
        "commandLine": subprocess.list2cmdline(argv),
        "argv": argv,
        "backendCommand": "run_authenticated_live_agent_proof_command",
        "backendPayload": {
            "backendCommand": "run_authenticated_live_agent_proof_command",
            "runtime": "agent-ui",
            "missionId": mission_id,
            "outDir": str(out_dir),
            "name": name,
            "timeoutMs": 120000,
        },
        "reason": target.get("action")
        or "Capture authenticated Agent UI screenshot evidence for the selected real-agent proof mission.",
        "targetKind": str(target.get("kind") or ""),
        "targetStatus": str(target.get("status") or ""),
        "source": "authenticated-live-agent-next-target",
    }


def _proof_next_command(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    target = (
        summary.get("nextProofTarget")
        if isinstance(summary.get("nextProofTarget"), dict)
        else _proof_next_target(summary)
    )
    runtime = _proof_command_runtime(summary, target)
    action = _compact_problem_text(target.get("action") or summary.get("nextProofAction") or summary.get("nextAction"))
    target_kind = str(target.get("kind") or "").strip()
    target_status = str(target.get("status") or "").strip()
    available = not (target_kind == "none" and target_status == "complete")
    if available:
        agent_ui_capture_command = _agent_ui_proof_capture_command(root, summary, target)
        if agent_ui_capture_command:
            return agent_ui_capture_command
    with_browser = bool(available and _proof_target_needs_browser(target))
    runtime_timeout = PROOF_COMMAND_TIMEOUTS.get(runtime, 90)
    argv = [
        sys.executable,
        "-m",
        "grant_agent.cli",
        "real-agent-proof-run",
        "--root",
        str(Path(root).resolve()),
        "--runtime",
        runtime,
        "--runtime-timeout",
        str(runtime_timeout),
    ]
    if with_browser:
        argv.append("--with-browser")
    return {
        "schema": PROOF_ACTION_COMMAND_SCHEMA,
        "available": available,
        "runtime": runtime if available else "",
        "runtimeTimeout": runtime_timeout if available else 0,
        "withBrowser": with_browser,
        "commandLine": subprocess.list2cmdline(argv) if available else "",
        "argv": argv if available else [],
        "backendCommand": "run_real_agent_runtime_proof_command" if available else "",
        "backendPayload": {
            "runtime": runtime,
            "runtimeTimeout": runtime_timeout,
            "withBrowser": with_browser,
        }
        if available
        else {},
        "reason": action if available else "No open real-agent proof target.",
        "targetKind": target_kind,
        "targetStatus": target_status,
        "source": "real-agent-proof-next-target",
    }


def _attach_next_command(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(summary.get("nextProofTarget"), dict):
        summary["nextProofTarget"] = _proof_next_target(summary)
    summary["nextProofCommand"] = _proof_next_command(root, summary)
    return summary


def _proof_bag_status_summary(report: dict[str, Any]) -> dict[str, Any]:
    bags = report.get("proofBags")
    if not isinstance(bags, dict) or not bags:
        return _empty_proof_bag_summary()

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for bag_id, raw_bag in bags.items():
        if not isinstance(raw_bag, dict):
            continue
        status = _normalized_proof_bag_status(raw_bag.get("status"))
        counts[status] = counts.get(status, 0) + 1
        row: dict[str, Any] = {
            "bagId": str(bag_id),
            "label": _proof_bag_label(str(bag_id), raw_bag),
            "status": status,
            "passed": bool(raw_bag.get("passed")) or status == "collected",
            "detail": _compact_problem_text(raw_bag.get("detail"), 320),
        }
        for key in ("runtime", "model", "screenshot", "sourcePath", "previewError"):
            value = str(raw_bag.get(key) or "").strip()
            if value:
                row[key] = _compact_problem_text(value, 320)
        rows.append(row)

    if not rows:
        return _empty_proof_bag_summary()

    blocked_rows = [row for row in rows if row["status"] == "blocked"]
    missing_rows = [row for row in rows if row["status"] == "missing"]
    skipped_rows = [row for row in rows if row["status"] == "skipped"]
    collected_count = counts.get("collected", 0)
    blocked_count = counts.get("blocked", 0)
    missing_count = counts.get("missing", 0)
    skipped_count = counts.get("skipped", 0)
    next_bag = (blocked_rows or missing_rows or skipped_rows or [{}])[0]
    report_summary = report.get("proofBagSummary") if isinstance(report.get("proofBagSummary"), dict) else {}
    raw_missing_or_skipped = report_summary.get("missingOrSkipped")
    raw_blocked = report_summary.get("blocked")
    missing_or_skipped = [
        str(item)
        for item in (raw_missing_or_skipped if isinstance(raw_missing_or_skipped, list) else [])
        if str(item or "").strip()
    ]
    blocked = [
        str(item)
        for item in (raw_blocked if isinstance(raw_blocked, list) else [])
        if str(item or "").strip()
    ]
    if not missing_or_skipped:
        missing_or_skipped = [str(row["label"]) for row in [*missing_rows, *skipped_rows]]
    if not blocked:
        blocked = [str(row["label"]) for row in blocked_rows]
    next_action = str(report.get("nextAction") or "").strip()
    if not next_action and next_bag:
        next_action = f"Resolve {next_bag.get('label')} before treating this runtime proof as complete."

    return {
        "schema": "fluxio.real_agent_proof_bag_status.v1",
        "total": len(rows),
        "counts": counts,
        "collectedCount": collected_count,
        "blockedCount": blocked_count,
        "missingCount": missing_count,
        "skippedCount": skipped_count,
        "incompleteCount": max(0, len(rows) - collected_count),
        "openCount": blocked_count + missing_count,
        "allCollected": len(rows) > 0 and collected_count == len(rows),
        "allClosed": len(rows) > 0 and all(row["status"] in {"collected", "blocked"} for row in rows),
        "rows": rows,
        "blocked": blocked,
        "missingOrSkipped": missing_or_skipped,
        "nextBag": next_bag,
        "nextAction": next_action,
        "source": "verifier-proof-bags",
    }


def _first_matching_check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    for item in checks:
        if isinstance(item, dict) and item.get("checkId") == check_id:
            return item
    return {}


def _report_runtime_ids(report: dict[str, Any]) -> list[str]:
    if report.get("schema") == MIXED_PROOF_SCHEMA or str(report.get("runtime") or "").lower() == "mixed":
        return ["mixed"]
    runtimes: list[str] = []
    explicit_runtime = str(report.get("runtime") or "").strip().lower()
    if explicit_runtime in RUNTIME_BAG_IDS:
        runtimes.append(explicit_runtime)
    for runtime, bag_id in RUNTIME_BAG_IDS.items():
        bag = _proof_bag(report, bag_id)
        status = str(bag.get("status") or "").lower()
        if status and status not in {"missing", "skipped"} and runtime not in runtimes:
            runtimes.append(runtime)
    for attempt in report.get("attempts") if isinstance(report.get("attempts"), list) else []:
        if not isinstance(attempt, dict):
            continue
        runtime = str(attempt.get("runtime") or "").strip().lower()
        if runtime in RUNTIME_BAG_IDS and runtime not in runtimes:
            runtimes.append(runtime)
    for check_id in ("real-agent-reply-captured", "real-agent-reply-is-substantive"):
        check = _first_matching_check(report, check_id)
        runtime = str(check.get("runtime") or "").strip().lower()
        if runtime in RUNTIME_BAG_IDS and runtime not in runtimes:
            runtimes.append(runtime)
    recovered = report.get("recoveredRuntimeReply") if isinstance(report.get("recoveredRuntimeReply"), dict) else {}
    if recovered and "openclaw" not in runtimes:
        runtimes.append("openclaw")
    return runtimes


def _compact_problem_text(value: object, limit: int = 260) -> str:
    body = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(body) <= limit:
        return body
    return body[: limit - 3].rstrip() + "..."


def _runtime_diagnostic_summary(report: dict[str, Any], runtime: str, limit: int = 320) -> str:
    if str(runtime or "").lower() != "openclaw":
        return ""
    diagnostic = report.get("openclawRuntimeDiagnostics")
    if not isinstance(diagnostic, dict):
        return ""
    summary = str(diagnostic.get("summary") or "").strip()
    if summary:
        return _compact_problem_text(summary, limit)
    problems = [
        str(item).strip()
        for item in diagnostic.get("problems", [])
        if str(item or "").strip()
    ]
    return _compact_problem_text("; ".join(problems), limit)


def _runtime_diagnostic_payload(report: dict[str, Any], runtime: str) -> dict[str, Any]:
    if str(runtime or "").lower() != "openclaw":
        return {}
    diagnostic = report.get("openclawRuntimeDiagnostics")
    return diagnostic if isinstance(diagnostic, dict) else {}


def summarize_proof_report(
    report: dict[str, Any],
    *,
    runtime_hint: str = "",
    report_path: Path | None = None,
    extra_screenshot_receipts: list[dict[str, Any]] | None = None,
    receipt_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    freshness = _proof_freshness_fields(report)
    evidence_receipt = _proof_report_file_receipt(report, report_path, receipt_cache=receipt_cache)
    screenshot_receipts = _merge_screenshot_receipts(
        _proof_screenshot_receipts(report, report_path, receipt_cache=receipt_cache),
        extra_screenshot_receipts or [],
    )
    evidence_health = _proof_evidence_health([evidence_receipt], screenshot_receipts)
    evidence_checklist = _proof_evidence_checklist(
        [evidence_receipt],
        screenshot_receipts,
        evidence_health=evidence_health,
        stale=bool(freshness.get("stale")),
    )
    runtime = str(runtime_hint or report.get("runtime") or "").strip().lower()
    if not runtime:
        runtimes = _report_runtime_ids(report)
        runtime = runtimes[0] if runtimes else "runtime"
    if runtime == "mixed":
        runs = report.get("runs") if isinstance(report.get("runs"), list) else []
        hermes = next((item for item in runs if isinstance(item, dict) and item.get("runtime") == "hermes"), {})
        openclaw = next((item for item in runs if isinstance(item, dict) and item.get("runtime") == "openclaw"), {})
        run_screenshot_receipts: list[dict[str, Any]] = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            if isinstance(run.get("proofScreenshotReceipts"), list):
                run_screenshot_receipts.extend(item for item in run["proofScreenshotReceipts"] if isinstance(item, dict))
            else:
                run_screenshot_receipts.extend(_proof_screenshot_receipts(run, report_path, receipt_cache=receipt_cache))
        screenshot_receipts = _merge_screenshot_receipts(screenshot_receipts, run_screenshot_receipts)
        evidence_health = _proof_evidence_health([evidence_receipt], screenshot_receipts)
        evidence_checklist = _proof_evidence_checklist(
            [evidence_receipt],
            screenshot_receipts,
            evidence_health=evidence_health,
            stale=bool(freshness.get("stale")),
        )
        status = str(report.get("status") or "unknown")
        proof_bag_summary = _proof_bag_status_summary(report)
        next_proof_action = proof_bag_summary["nextAction"] or report.get("nextAction") or ""
        mixed_transcript_receipt = _empty_transcript_receipt("mixed")
        transcript_runtime_coverage = _mixed_runtime_transcript_coverage(
            [item for item in (hermes, openclaw) if isinstance(item, dict)]
        )
        mixed_real_runtime_output = bool(transcript_runtime_coverage["anyRuntimeTranscriptOutput"])
        mixed_all_runtime_output = bool(transcript_runtime_coverage["allRuntimeTranscriptsReal"])
        mixed_fresh_runtime_output = bool(transcript_runtime_coverage["allRuntimeTranscriptsFresh"])
        run_transcript_lines = [
            str((item.get("proofTranscriptReceipt") or {}).get("summaryLine") or "").strip()
            for item in (hermes, openclaw)
            if isinstance(item, dict)
            and isinstance(item.get("proofTranscriptReceipt"), dict)
            and str((item.get("proofTranscriptReceipt") or {}).get("summaryLine") or "").strip()
        ]
        if mixed_real_runtime_output:
            mixed_transcript_receipt.update(
                {
                    "status": "fresh" if mixed_fresh_runtime_output else "partial",
                    "source": "mixed-runtime-proof",
                    "sourceLabel": "Mixed runtime proof",
                    "freshRuntimeOutput": mixed_fresh_runtime_output,
                    "realRuntimeOutput": mixed_real_runtime_output,
                    "hasRealTranscript": mixed_real_runtime_output,
                    "allRuntimeTranscriptsReal": mixed_all_runtime_output,
                    "allRuntimeTranscriptsFresh": mixed_fresh_runtime_output,
                    "runtimeCoverage": transcript_runtime_coverage,
                    "summaryLine": _summary_line([transcript_runtime_coverage["summaryLine"], *run_transcript_lines])
                    or "Mixed runtime proof contains real runtime transcript output.",
                    "reportPath": str(report_path or report.get("reportPath") or ""),
                }
            )
        summary: dict[str, Any] = {
            "runtime": "mixed",
            "label": "Mixed Hermes/OpenClaw",
            "status": status,
            "tone": "good" if status == "passed" else "warn" if status == "partial" else "bad",
            "freshRuntimeOutput": bool(hermes.get("freshRuntimeOutput")) and bool(openclaw.get("freshRuntimeOutput")),
            "realRuntimeOutput": bool(hermes.get("realRuntimeOutput")) and bool(openclaw.get("realRuntimeOutput")),
            "anyRuntimeTranscriptOutput": mixed_real_runtime_output,
            "allRuntimeTranscriptOutput": mixed_all_runtime_output,
            "transcriptRuntimeCoverage": transcript_runtime_coverage,
            "transcriptCoverageLine": transcript_runtime_coverage["summaryLine"],
            "hermesStatus": hermes.get("status") or "unknown",
            "openclawStatus": openclaw.get("status") or "unknown",
            "createdAt": report.get("createdAt") or "",
            "checkedAt": report.get("checkedAt") or "",
            "reportPath": str(report_path or report.get("reportPath") or ""),
            "proofEvidenceReceipt": evidence_receipt,
            "reportSha256": evidence_receipt["sha256"],
            "reportSizeBytes": evidence_receipt["sizeBytes"],
            "proofScreenshotReceipts": screenshot_receipts,
            "proofScreenshotReceiptCount": len(screenshot_receipts),
            "missingProofScreenshotReceiptCount": len([item for item in screenshot_receipts if not item.get("exists")]),
            "proofEvidenceHealth": evidence_health,
            "proofEvidenceChecklist": evidence_checklist,
            "evidenceStatus": evidence_health["status"],
            "nextEvidenceAction": evidence_health["nextEvidenceAction"],
            **freshness,
            "proofBagSummary": proof_bag_summary,
            "proofBagRows": proof_bag_summary["rows"],
            "nextProofAction": next_proof_action,
            "nextAction": report.get("nextAction") or "",
            "headline": report.get("headline") or "Mixed proof has not run yet.",
            "proofTranscriptReceipt": mixed_transcript_receipt,
            "transcriptStatus": mixed_transcript_receipt["status"],
            "transcriptSource": mixed_transcript_receipt["source"],
            "transcriptSummaryLine": mixed_transcript_receipt["summaryLine"],
            "runs": runs,
            "source": "mixed-verifier-run",
        }
        summary["nextProofTarget"] = _proof_next_target(summary)
        return summary

    proof_bag_summary = _proof_bag_status_summary(report)
    fresh_bag = _proof_bag(report, RUNTIME_BAG_IDS.get(runtime, ""))
    recovered_bag = _proof_bag(report, "recovered_openclaw_session")
    fresh_status = str(fresh_bag.get("status") or "").lower()
    recovered_status = str(recovered_bag.get("status") or "").lower()
    report_status = str(report.get("status") or "").lower()
    selected_capture_modes = []
    mission_summary = report.get("missionDetailSummary") if isinstance(report.get("missionDetailSummary"), dict) else {}
    raw_capture_modes = mission_summary.get("dialogueCaptureModes") if isinstance(mission_summary.get("dialogueCaptureModes"), list) else []
    selected_capture_modes = [str(item) for item in raw_capture_modes if str(item or "").strip()]
    fresh_runtime_output = fresh_status == "collected"
    recovered_runtime_output = runtime == "openclaw" and recovered_status == "collected" and not fresh_runtime_output
    real_runtime_output = fresh_runtime_output or recovered_runtime_output or bool(mission_summary.get("dialogueCount"))
    blocker = ""
    if fresh_status == "blocked":
        blocker = _compact_problem_text(fresh_bag.get("detail"))
    elif not real_runtime_output:
        blocker = _compact_problem_text(report.get("nextAction"))
    diagnostic_summary = _runtime_diagnostic_summary(report, runtime)
    if runtime == "openclaw" and diagnostic_summary and not fresh_runtime_output:
        blocker = diagnostic_summary
    if fresh_runtime_output:
        status = "passed" if report_status == "passed" else "partial"
        tone = "good"
        headline = f"{runtime.title()} fresh runtime output captured."
    elif recovered_runtime_output:
        status = "partial"
        tone = "warn"
        headline = (
            "OpenClaw fresh run is blocked; recovered persisted output is available. "
            + diagnostic_summary
            if diagnostic_summary
            else "OpenClaw fresh run is blocked; recovered persisted output is available."
        )
    else:
        status = "blocked" if fresh_status == "blocked" or report_status == "blocked" else report_status or "unknown"
        tone = "bad" if status == "blocked" else "warn"
        headline = (
            "OpenClaw fresh runtime is blocked: " + diagnostic_summary
            if runtime == "openclaw" and diagnostic_summary
            else blocker or f"{runtime.title()} proof has not collected fresh runtime output."
        )
    screenshots = report.get("screenshots") if isinstance(report.get("screenshots"), dict) else {}
    attempts = report.get("attempts") if isinstance(report.get("attempts"), list) else []
    latest_attempt = next((item for item in reversed(attempts) if isinstance(item, dict) and str(item.get("runtime") or "").lower() == runtime), {})
    next_proof_action = proof_bag_summary["nextAction"] or report.get("nextAction") or ""
    proof_transcript_receipt = _runtime_transcript_receipt(
        report,
        runtime=runtime,
        fresh_bag=fresh_bag,
        recovered_bag=recovered_bag,
        mission_summary=mission_summary,
        latest_attempt=latest_attempt,
        blocker=blocker,
        report_path=report_path,
    )
    summary = {
        "runtime": runtime,
        "label": "OpenClaw" if runtime == "openclaw" else "Hermes" if runtime == "hermes" else runtime.title(),
        "status": status,
        "tone": tone,
        "headline": headline,
        "createdAt": report.get("createdAt") or "",
        "reportPath": str(report_path or report.get("reportPath") or ""),
        "proofEvidenceReceipt": evidence_receipt,
        "reportSha256": evidence_receipt["sha256"],
        "reportSizeBytes": evidence_receipt["sizeBytes"],
        "proofScreenshotReceipts": screenshot_receipts,
        "proofScreenshotReceiptCount": len(screenshot_receipts),
        "missingProofScreenshotReceiptCount": len([item for item in screenshot_receipts if not item.get("exists")]),
        "proofEvidenceHealth": evidence_health,
        "proofEvidenceChecklist": evidence_checklist,
        "evidenceStatus": evidence_health["status"],
        "nextEvidenceAction": evidence_health["nextEvidenceAction"],
        **freshness,
        "runtimeSessionId": report.get("runtimeSessionId") or "",
        "missionId": (report.get("mission") or {}).get("missionId") if isinstance(report.get("mission"), dict) else "",
        "freshStatus": fresh_status or "missing",
        "recoveredStatus": recovered_status or "missing",
        "freshRuntimeOutput": fresh_runtime_output,
        "recoveredRuntimeOutput": recovered_runtime_output,
        "realRuntimeOutput": real_runtime_output,
        "corePassed": bool(report.get("corePassed")),
        "passed": bool(report.get("passed")),
        "blocker": blocker,
        "diagnosticSummary": diagnostic_summary,
        "runtimeDiagnostics": _runtime_diagnostic_payload(report, runtime),
        "proofBagSummary": proof_bag_summary,
        "proofBagRows": proof_bag_summary["rows"],
        "nextProofAction": next_proof_action,
        "nextAction": report.get("nextAction") or "",
        "captureModes": selected_capture_modes,
        "dialogueCount": int(mission_summary.get("dialogueCount") or 0),
        "artifactGatePassed": bool(mission_summary.get("artifactGatePassed")),
        "screenshots": screenshots,
        "agentScreenshot": screenshots.get("agentConversation") or "",
        "producedOutputScreenshot": screenshots.get("producedOutputPreview") or "",
        "attemptTimedOut": bool(latest_attempt.get("timedOut")),
        "attemptDurationMs": int(latest_attempt.get("durationMs") or 0),
        "attemptModel": latest_attempt.get("model") or fresh_bag.get("model") or "",
        "proofTranscriptReceipt": proof_transcript_receipt,
        "transcriptStatus": proof_transcript_receipt["status"],
        "transcriptSource": proof_transcript_receipt["source"],
        "transcriptSummaryLine": proof_transcript_receipt["summaryLine"],
        "source": "verifier-report",
    }
    summary["nextProofTarget"] = _proof_next_target(summary)
    return summary


def _proof_run_timeline(report_summaries: list[dict[str, Any]], *, limit: int = 12) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    for index, summary in enumerate(report_summaries):
        if not isinstance(summary, dict):
            continue
        evidence_health = summary.get("proofEvidenceHealth") if isinstance(summary.get("proofEvidenceHealth"), dict) else {}
        next_target = summary.get("nextProofTarget") if isinstance(summary.get("nextProofTarget"), dict) else _proof_next_target(summary)
        transcript_receipt = (
            summary.get("proofTranscriptReceipt")
            if isinstance(summary.get("proofTranscriptReceipt"), dict)
            else _empty_transcript_receipt(str(summary.get("runtime") or ""))
        )
        next_action = (
            next_target.get("action")
            or summary.get("nextEvidenceAction")
            or summary.get("nextProofAction")
            or summary.get("nextAction")
            or ""
        )
        next_command = (
            summary.get("nextProofCommand")
            if isinstance(summary.get("nextProofCommand"), dict)
            else {}
        )
        evidence_checklist = (
            summary.get("proofEvidenceChecklist")
            if isinstance(summary.get("proofEvidenceChecklist"), dict)
            else {}
        )
        checklist_next_missing = (
            evidence_checklist.get("nextMissing")
            if isinstance(evidence_checklist.get("nextMissing"), dict)
            else {}
        )
        all_rows.append(
            {
                "index": index + 1,
                "runtime": summary.get("runtime") or "",
                "label": summary.get("label") or "",
                "status": summary.get("status") or "unknown",
                "tone": summary.get("tone") or "neutral",
                "createdAt": summary.get("createdAt") or summary.get("checkedAt") or "",
                "proofFreshness": summary.get("proofFreshness") or "unknown",
                "stale": bool(summary.get("stale")),
                "freshRuntimeOutput": bool(summary.get("freshRuntimeOutput")),
                "realRuntimeOutput": bool(summary.get("realRuntimeOutput")),
                "anyRuntimeTranscriptOutput": bool(
                    summary.get("anyRuntimeTranscriptOutput")
                    or transcript_receipt.get("hasRealTranscript")
                    or transcript_receipt.get("realRuntimeOutput")
                ),
                "allRuntimeTranscriptOutput": bool(
                    summary.get("allRuntimeTranscriptOutput")
                    or (
                        summary.get("runtime") != "mixed"
                        and summary.get("realRuntimeOutput")
                    )
                ),
                "transcriptRuntimeCoverage": summary.get("transcriptRuntimeCoverage")
                if isinstance(summary.get("transcriptRuntimeCoverage"), dict)
                else transcript_receipt.get("runtimeCoverage")
                if isinstance(transcript_receipt.get("runtimeCoverage"), dict)
                else {},
                "evidenceStatus": summary.get("evidenceStatus") or evidence_health.get("status") or "",
                "allEvidenceAttached": bool(evidence_health.get("allEvidenceAttached")),
                "reportAttachedCount": int(evidence_health.get("reportAttachedCount") or 0),
                "screenshotAttachedCount": int(evidence_health.get("screenshotAttachedCount") or 0),
                "screenshotReceiptCount": int(summary.get("proofScreenshotReceiptCount") or 0),
                "missingRequiredScreenshotCount": int(evidence_health.get("missingRequiredScreenshotCount") or 0),
                "proofTranscriptReceipt": transcript_receipt,
                "transcriptStatus": transcript_receipt.get("status") or "missing",
                "transcriptSource": transcript_receipt.get("source") or "missing",
                "transcriptSummaryLine": transcript_receipt.get("summaryLine") or "",
                "reportPath": summary.get("reportPath") or "",
                "reportSha256": summary.get("reportSha256") or "",
                "nextProofTarget": next_target,
                "nextProofCommand": next_command,
                "proofEvidenceChecklist": evidence_checklist,
                "evidenceChecklistMissingCount": int(evidence_checklist.get("missingCount") or 0),
                "evidenceChecklistNextMissingId": checklist_next_missing.get("id") or "",
                "headline": _compact_problem_text(summary.get("headline"), 220),
                "nextAction": _compact_problem_text(next_action, 260),
            }
        )
    rows = all_rows[:limit]
    latest_complete = next((row for row in all_rows if row["allEvidenceAttached"]), {})
    latest_fresh = next((row for row in all_rows if row["proofFreshness"] == "fresh"), {})
    return {
        "schema": PROOF_RUN_TIMELINE_SCHEMA,
        "total": len(all_rows),
        "returnedCount": len(rows),
        "limit": limit,
        "completeCount": len([row for row in all_rows if row["allEvidenceAttached"]]),
        "freshCount": len([row for row in all_rows if row["proofFreshness"] == "fresh"]),
        "staleCount": len([row for row in all_rows if row["stale"]]),
        "blockedCount": len([row for row in all_rows if row["status"] == "blocked"]),
        "latestCompleteReportPath": latest_complete.get("reportPath") or "",
        "latestFreshReportPath": latest_fresh.get("reportPath") or "",
        "rows": rows,
    }


def build_real_agent_proof_status(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    out_dir = proof_out_dir(root)
    proof_roots = _candidate_proof_roots(root)
    indexed_paths, proof_report_index = _load_proof_report_index(root)
    receipt_cache = _load_proof_receipt_cache(root)
    agent_report_indexes: dict[str, dict[str, list[tuple[dict[str, Any], Path]]]] = {}
    for proof_root in proof_roots:
        agent_report_indexes[str(proof_root)] = _authenticated_live_agent_report_index(proof_root)
    reconciled_receipt_cache: dict[str, list[dict[str, Any]]] = {}

    def reconciled_screenshot_receipts(report: dict[str, Any], path: Path, report_root: Path) -> list[dict[str, Any]]:
        try:
            cache_key = f"{report_root.resolve()}::{path.resolve()}"
        except OSError:
            cache_key = f"{report_root}::{path}"
        if cache_key not in reconciled_receipt_cache:
            reconciled_receipt_cache[cache_key] = _reconciled_screenshot_receipts(
                report_root,
                report,
                report_path=path,
                receipt_cache=receipt_cache,
                agent_report_index=agent_report_indexes.get(str(report_root), {}),
            )
        return reconciled_receipt_cache[cache_key]

    primary_index_hit = proof_report_index.get("status") == "hit"
    source_root_rows: list[dict[str, Any]] = []
    path_map: dict[str, tuple[Path, Path]] = {}
    full_scan_root_count = 0
    for proof_root in proof_roots:
        root_out_dir = proof_out_dir(proof_root)
        root_indexed_paths, root_index = (
            (indexed_paths, proof_report_index)
            if proof_root == root
            else _load_proof_report_index(proof_root)
        )
        root_use_index = root_index.get("status") == "hit"
        root_candidate_paths = [
            root_out_dir / "latest.json",
            root_out_dir / "mixed-latest.json",
            *root_indexed_paths,
        ]
        full_scan = not root_use_index and not primary_index_hit
        if full_scan:
            full_scan_root_count += 1
            root_candidate_paths.extend(
                [
                    *root_out_dir.glob("*/real-agent-conversation-check.json"),
                    *root_out_dir.glob("*/mixed-real-agent-runtime-proof.json"),
                ]
            )
        source_root_rows.append(
            {
                "root": str(proof_root),
                "outDir": str(root_out_dir),
                "indexStatus": root_index.get("status") or "miss",
                "scanMode": "full" if full_scan else "indexed",
                "configured": proof_root != root,
                "candidatePathCount": len(root_candidate_paths),
            }
        )
        for candidate in root_candidate_paths:
            owner_root = _owner_root_for_path(candidate, proof_roots, proof_root)
            try:
                key = str(candidate.resolve())
            except OSError:
                key = str(candidate)
            if candidate.exists():
                path_map[key] = (candidate, owner_root)
    if full_scan_root_count == 0:
        scan_mode = "indexed"
    elif full_scan_root_count == len(proof_roots):
        scan_mode = "full"
    else:
        scan_mode = "mixed"
    reports: list[tuple[dict[str, Any], Path, Path]] = []
    for path, report_root in path_map.values():
        report = _read_json(path)
        if report:
            reports.append((report, _preferred_report_path(report, path), report_root))
    reports.sort(key=lambda item: _created_sort_key(item[0], item[1]), reverse=True)
    deduped_reports: list[tuple[dict[str, Any], Path, Path]] = []
    seen_report_keys: set[str] = set()
    for report, path, report_root in reports:
        key = _logical_report_key(report, path)
        if key in seen_report_keys:
            continue
        seen_report_keys.add(key)
        deduped_reports.append((report, path, report_root))
    reports = deduped_reports
    runtime_rows: dict[str, dict[str, Any]] = {}
    for report, path, report_root in reports:
        runtime_ids = _report_runtime_ids(report)
        if not any(runtime in SUPPORTED_PROOF_RUNTIMES and runtime not in runtime_rows for runtime in runtime_ids):
            continue
        extra_screenshot_receipts = reconciled_screenshot_receipts(report, path, report_root)
        for runtime in runtime_ids:
            if runtime not in SUPPORTED_PROOF_RUNTIMES or runtime in runtime_rows:
                continue
            runtime_rows[runtime] = summarize_proof_report(
                report,
                runtime_hint=runtime,
                report_path=path,
                extra_screenshot_receipts=extra_screenshot_receipts,
                receipt_cache=receipt_cache,
            )
    rows = [
        runtime_rows.get(runtime)
        or {
            "runtime": runtime,
            "label": "Mixed Hermes/OpenClaw" if runtime == "mixed" else "OpenClaw" if runtime == "openclaw" else "Hermes",
            "status": "missing",
            "tone": "neutral",
            "headline": "No verifier report has been captured yet.",
            "freshRuntimeOutput": False,
            "realRuntimeOutput": False,
            "reportPath": "",
            "proofEvidenceReceipt": _proof_report_file_receipt({}),
            "reportSha256": "",
            "reportSizeBytes": 0,
            "proofScreenshotReceipts": [],
            "proofScreenshotReceiptCount": 0,
            "missingProofScreenshotReceiptCount": 0,
            "proofEvidenceHealth": _proof_evidence_health([], []),
            "proofEvidenceChecklist": _proof_evidence_checklist(
                [],
                [],
                evidence_health=_proof_evidence_health([], []),
            ),
            "evidenceStatus": "missing_report",
            "nextEvidenceAction": "Run the real-agent verifier so Neyvia can attach a JSON proof report.",
            "proofFreshness": "missing",
            "proofAgeSeconds": None,
            "stale": False,
            "staleAfterSeconds": PROOF_STALE_AFTER_SECONDS,
            "proofBagSummary": _empty_proof_bag_summary(),
            "proofBagRows": [],
            "nextProofAction": "",
            "proofTranscriptReceipt": _empty_transcript_receipt(runtime),
            "transcriptStatus": "missing",
            "transcriptSource": "missing",
            "transcriptSummaryLine": "No real runtime transcript has been recorded.",
        }
        for runtime in ("hermes", "openclaw", "mixed")
    ]
    for row in rows:
        if isinstance(row, dict) and not isinstance(row.get("nextProofTarget"), dict):
            row["nextProofTarget"] = _proof_next_target(row)
            row["nextProofAction"] = row.get("nextProofAction") or row["nextProofTarget"].get("action") or ""
        if isinstance(row, dict):
            _attach_next_command(root, row)
    report_summaries = [
        summarize_proof_report(
            report,
            runtime_hint=(_report_runtime_ids(report) or [""])[0],
            report_path=path,
            extra_screenshot_receipts=reconciled_screenshot_receipts(report, path, report_root),
            receipt_cache=receipt_cache,
        )
        for report, path, report_root in reports
    ]
    for summary in report_summaries:
        _attach_next_command(root, summary)
    latest_summary = report_summaries[0] if report_summaries else {}
    latest_screenshot_summary = next(
        (
            summary
            for summary in report_summaries
            if isinstance(summary.get("proofScreenshotReceipts"), list)
            and summary["proofScreenshotReceipts"]
        ),
        {},
    )
    latest_complete_summary = next(
        (
            summary
            for summary in report_summaries
            if isinstance(summary.get("proofEvidenceHealth"), dict)
            and summary["proofEvidenceHealth"].get("allEvidenceAttached")
        ),
        {},
    )
    proof_run_timeline = _proof_run_timeline(report_summaries)
    proof_transcript_receipts = [
        summary["proofTranscriptReceipt"]
        for summary in report_summaries
        if isinstance(summary.get("proofTranscriptReceipt"), dict)
    ]
    proof_transcript_health = _proof_transcript_health(proof_transcript_receipts)
    latest_transcript_summary = next(
        (
            summary
            for summary in report_summaries
            if isinstance(summary.get("proofTranscriptReceipt"), dict)
            and str(summary["proofTranscriptReceipt"].get("status") or "") != "missing"
        ),
        {},
    )
    proof_evidence_receipts = _merge_evidence_receipts(
        [
            item.get("proofEvidenceReceipt")
            for item in rows
            if isinstance(item.get("proofEvidenceReceipt"), dict)
            and str(item.get("reportPath") or "").strip()
        ]
    )
    proof_screenshot_receipts = _merge_screenshot_receipts(
        *[
            item.get("proofScreenshotReceipts")
            for item in rows
            if isinstance(item.get("proofScreenshotReceipts"), list)
        ]
    )
    proof_evidence_health = _proof_evidence_health(proof_evidence_receipts, proof_screenshot_receipts)
    proof_evidence_checklist = _proof_evidence_checklist(
        proof_evidence_receipts,
        proof_screenshot_receipts,
        evidence_health=proof_evidence_health,
    )
    next_proof_target = _proof_next_target(
        latest_summary
        if latest_summary
        else {
            "runtime": "",
            "proofEvidenceHealth": proof_evidence_health,
            "evidenceStatus": proof_evidence_health["status"],
            "nextEvidenceAction": proof_evidence_health["nextEvidenceAction"],
            "proofBagSummary": _empty_proof_bag_summary(),
            "reportPath": "",
        }
    )
    next_proof_command = _proof_next_command(
        root,
        {
            **(latest_summary if latest_summary else {}),
            "nextProofTarget": next_proof_target,
            "proofEvidenceHealth": latest_summary.get("proofEvidenceHealth", proof_evidence_health)
            if latest_summary
            else proof_evidence_health,
            "evidenceStatus": latest_summary.get("evidenceStatus", proof_evidence_health["status"])
            if latest_summary
            else proof_evidence_health["status"],
            "nextEvidenceAction": latest_summary.get("nextEvidenceAction", proof_evidence_health["nextEvidenceAction"])
            if latest_summary
            else proof_evidence_health["nextEvidenceAction"],
        },
    )
    if (
        _proof_checklist_next_missing_id({"proofEvidenceChecklist": proof_evidence_checklist}) == "agent_ui_screenshot"
        and next_proof_command.get("backendCommand") != "run_authenticated_live_agent_proof_command"
    ):
        row_agent_ui_command = next(
            (
                item.get("nextProofCommand")
                for item in rows
                if isinstance(item, dict)
                and isinstance(item.get("nextProofCommand"), dict)
                and item["nextProofCommand"].get("backendCommand") == "run_authenticated_live_agent_proof_command"
            ),
            {},
        )
        if row_agent_ui_command:
            next_proof_command = row_agent_ui_command
    proof_run_lock = _proof_run_lock_status(root)
    proof_report_index = {
        **proof_report_index,
        "candidatePathCount": len(path_map),
        "reportCount": len(reports),
        "scanMode": scan_mode,
        "sourceRootCount": len(proof_roots),
        "sourceRoots": source_root_rows,
    }
    if reports:
        _write_proof_report_index(
            root,
            report_summaries=report_summaries,
            proof_run_timeline=proof_run_timeline,
            latest_summary=latest_summary,
            latest_screenshot_summary=latest_screenshot_summary,
            latest_complete_summary=latest_complete_summary,
            latest_transcript_summary=latest_transcript_summary,
        )
    _write_proof_receipt_cache(root, receipt_cache)
    proof_receipt_cache = _proof_receipt_cache_status(receipt_cache)
    latest_report_path = str(latest_summary.get("reportPath") or "")
    latest_complete_report_path = str(latest_complete_summary.get("reportPath") or "")
    latest_report_has_complete_evidence = bool(
        latest_summary
        and latest_complete_summary
        and latest_report_path
        and latest_report_path == latest_complete_report_path
    )
    if latest_report_has_complete_evidence:
        proof_bundle_status_value = "complete"
        proof_bundle_label = "Complete evidence bundle"
    elif latest_complete_summary:
        proof_bundle_status_value = "complete_available"
        proof_bundle_label = "Complete evidence bundle available"
    else:
        proof_bundle_status_value = str(proof_evidence_health.get("status") or "missing")
        proof_bundle_label = (
            "Evidence bundle incomplete"
            if proof_bundle_status_value not in {"complete", "missing_report", "missing"}
            else proof_bundle_status_value.replace("_", " ").title()
        )
    proof_bundle_status = {
        "schema": "fluxio.real_agent_proof_bundle_status.v1",
        "status": proof_bundle_status_value,
        "label": proof_bundle_label,
        "complete": bool(latest_complete_summary),
        "latestReportComplete": latest_report_has_complete_evidence,
        "latestReportPath": latest_report_path,
        "latestCompleteReportPath": latest_complete_report_path,
        "latestRuntimeStatus": str(latest_summary.get("status") or ""),
        "latestEvidenceStatus": str(latest_summary.get("evidenceStatus") or ""),
        "aggregateEvidenceStatus": str(proof_evidence_health.get("status") or ""),
        "completeCount": int(proof_run_timeline.get("completeCount") or 0),
        "nextAction": (
            "Open the latest complete proof mission or continue with the next proof target."
            if latest_complete_summary
            else proof_evidence_health["nextEvidenceAction"]
        ),
    }
    return {
        "schema": PROOF_STATUS_SCHEMA,
        "checkedAt": _utc_now(),
        "root": str(root),
        "outDir": str(out_dir),
        "proofSourceRootCount": len(proof_roots),
        "proofSourceRoots": source_root_rows,
        "proofRunLock": proof_run_lock,
        "proofRunInProgress": bool(proof_run_lock.get("running")),
        "latest": latest_summary,
        "latestScreenshotProof": latest_screenshot_summary,
        "latestCompleteProof": latest_complete_summary,
        "latestTranscriptProof": latest_transcript_summary,
        "latestProofTranscriptReceipt": latest_transcript_summary.get("proofTranscriptReceipt") or _empty_transcript_receipt(),
        "proofTranscriptReceipts": proof_transcript_receipts,
        "proofTranscriptReceiptCount": len(proof_transcript_receipts),
        "proofTranscriptHealth": proof_transcript_health,
        "transcriptHealthStatus": proof_transcript_health["status"],
        "hasRealTranscriptProof": bool(proof_transcript_health["hasRealTranscript"]),
        "hasFreshTranscriptProof": bool(proof_transcript_health["hasFreshTranscript"]),
        "nextTranscriptAction": proof_transcript_health["nextTranscriptAction"],
        "hasCompleteEvidenceBundle": bool(latest_complete_summary),
        "proofBundleStatus": proof_bundle_status,
        "latestProofEvidenceReceipt": latest_summary.get("proofEvidenceReceipt") or _proof_report_file_receipt({}),
        "proofEvidenceReceipts": proof_evidence_receipts,
        "missingProofEvidenceReceiptCount": len([item for item in proof_evidence_receipts if not item.get("exists")]),
        "proofScreenshotReceipts": proof_screenshot_receipts,
        "proofScreenshotReceiptCount": len(proof_screenshot_receipts),
        "missingProofScreenshotReceiptCount": len([item for item in proof_screenshot_receipts if not item.get("exists")]),
        "proofEvidenceHealth": proof_evidence_health,
        "proofEvidenceChecklist": proof_evidence_checklist,
        "evidenceStatus": proof_evidence_health["status"],
        "nextEvidenceAction": proof_evidence_health["nextEvidenceAction"],
        "nextProofTarget": next_proof_target,
        "nextProofAction": next_proof_target.get("action") or proof_evidence_health["nextEvidenceAction"],
        "nextProofCommand": next_proof_command,
        "proofBagSummary": latest_summary.get("proofBagSummary") or _empty_proof_bag_summary(),
        "proofRunTimeline": proof_run_timeline,
        "proofRunTimelineRows": proof_run_timeline["rows"],
        "runtimes": {str(item["runtime"]): item for item in rows},
        "runtimeRows": rows,
        "reportCount": len(reports),
        "proofReportIndex": proof_report_index,
        "proofReceiptCache": proof_receipt_cache,
        "staleAfterSeconds": PROOF_STALE_AFTER_SECONDS,
        "hasStaleProof": any(bool(item.get("stale")) for item in rows),
        "staleRuntimeCount": len([item for item in rows if item.get("stale")]),
        "source": "real-agent-verifier-reports",
    }


def _run_verifier_once(
    root: Path,
    runtime: str,
    *,
    runtime_timeout: int,
    with_browser: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    script = Path(root).resolve() / "scripts" / "verify_real_agent_conversation_proof.py"
    if not script.exists():
        raise RuntimeError(f"Real agent conversation verifier is missing: {script}")
    args = [
        sys.executable,
        str(script),
        "--root",
        str(Path(root).resolve()),
        "--out-dir",
        str(proof_out_dir(root)),
        "--runtime",
        runtime,
        "--fresh-runtime",
        "--runtime-timeout",
        str(runtime_timeout),
    ]
    if with_browser:
        args.append("--with-browser")
    env = os.environ.copy()
    env.update(extra_env or {})
    started = time.perf_counter()
    process_timeout = max(runtime_timeout + 90, 180 if not with_browser else 360)
    completed = subprocess.run(  # noqa: S603
        args,
        cwd=str(Path(root).resolve()),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=process_timeout,
        check=False,
        **hidden_windows_subprocess_kwargs(),
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    report = _parse_json_payload(completed.stdout, completed.stderr)
    if not report:
        latest = _read_json(proof_out_dir(root) / "latest.json")
        report = latest if latest else {}
    if not report:
        report = {
            "schema": "fluxio.real_agent_conversation_proof.v1",
            "createdAt": _utc_now(),
            "root": str(Path(root).resolve()),
            "runtime": runtime,
            "status": "blocked",
            "passed": False,
            "corePassed": False,
            "nextAction": _compact_problem_text(completed.stderr or completed.stdout or "Verifier did not return a report."),
        }
    report_path = Path(str(report.get("reportPath") or "")) if str(report.get("reportPath") or "").strip() else None
    summary = summarize_proof_report(
        report,
        runtime_hint=runtime,
        report_path=report_path,
        extra_screenshot_receipts=_reconciled_screenshot_receipts(root, report, report_path=report_path),
    )
    return {
        "runtime": runtime,
        "returnCode": completed.returncode,
        "elapsedMs": elapsed_ms,
        "ok": completed.returncode == 0,
        "report": report,
        "summary": summary,
        "stdoutPreview": _compact_problem_text(completed.stdout, 400),
        "stderrPreview": _compact_problem_text(completed.stderr, 400),
    }


def _write_mixed_report(root: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [run.get("summary") for run in runs if isinstance(run.get("summary"), dict)]
    hermes = next((item for item in summaries if item.get("runtime") == "hermes"), {})
    openclaw = next((item for item in summaries if item.get("runtime") == "openclaw"), {})
    hermes_fresh = bool(hermes.get("freshRuntimeOutput"))
    openclaw_fresh = bool(openclaw.get("freshRuntimeOutput"))
    openclaw_real = bool(openclaw.get("realRuntimeOutput"))
    if hermes_fresh and openclaw_fresh:
        status = "passed"
        headline = "Hermes and OpenClaw both produced fresh runtime output."
        next_action = "Use the Agent conversation surface; both runtime proof paths are fresh."
    elif hermes_fresh and openclaw_real:
        status = "partial"
        headline = "Hermes produced fresh output; OpenClaw is real but recovered or blocked for fresh output."
        next_action = str(openclaw.get("blocker") or openclaw.get("nextAction") or "Fix OpenClaw fresh runtime output.")
    else:
        status = "blocked"
        headline = "Mixed proof did not collect both runtime paths."
        next_action = str(openclaw.get("blocker") or hermes.get("blocker") or "Run Hermes and OpenClaw proof again after fixing runtime setup.")
    report = {
        "schema": MIXED_PROOF_SCHEMA,
        "createdAt": _utc_now(),
        "root": str(Path(root).resolve()),
        "runtime": "mixed",
        "status": status,
        "passed": status == "passed",
        "headline": headline,
        "nextAction": next_action,
        "runs": summaries,
        "checks": [
            {
                "checkId": "mixed-hermes-fresh-runtime-output",
                "passed": hermes_fresh,
                "detail": hermes.get("headline") or "No Hermes proof summary.",
            },
            {
                "checkId": "mixed-openclaw-fresh-runtime-output",
                "passed": openclaw_fresh,
                "detail": openclaw.get("headline") or "No OpenClaw proof summary.",
            },
        ],
        "source": "sequential-real-verifier-runs",
    }
    out_dir = proof_out_dir(root)
    run_dir = out_dir / f"mixed-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    report_path = run_dir / "mixed-real-agent-runtime-proof.json"
    report["reportPath"] = str(report_path)
    _write_json(report_path, report)
    _write_json(out_dir / "mixed-latest.json", report)
    return report


def run_real_agent_proof(
    root: Path,
    runtime: str,
    *,
    runtime_timeout: int = 90,
    with_browser: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    runtime = str(runtime or "hermes").strip().lower()
    if runtime not in SUPPORTED_PROOF_RUNTIMES:
        raise RuntimeError(f"Unsupported real agent proof runtime: {runtime}")
    runtime_timeout = _safe_int(runtime_timeout, 90, minimum=10, maximum=900)
    lock, acquired = _acquire_proof_run_lock(
        root,
        runtime=runtime,
        runtime_timeout=runtime_timeout,
        with_browser=with_browser,
    )
    if not acquired:
        return _proof_run_already_running_payload(root, runtime, lock)
    result: dict[str, Any]
    try:
        if runtime == "mixed":
            runs = [
                _run_verifier_once(root, "hermes", runtime_timeout=max(runtime_timeout, 120), with_browser=with_browser, extra_env=extra_env),
                _run_verifier_once(root, "openclaw", runtime_timeout=runtime_timeout, with_browser=False, extra_env=extra_env),
            ]
            mixed_report = _write_mixed_report(root, runs)
            result = {
                "schema": PROOF_RUN_SCHEMA,
                "runtime": "mixed",
                "status": mixed_report.get("status") or "unknown",
                "ok": bool(mixed_report.get("passed")),
                "alreadyRunning": False,
                "lock": lock,
                "report": mixed_report,
                "summary": summarize_proof_report(
                    mixed_report,
                    runtime_hint="mixed",
                    report_path=Path(str(mixed_report.get("reportPath") or "")),
                    extra_screenshot_receipts=_reconciled_screenshot_receipts(
                        root,
                        mixed_report,
                        report_path=Path(str(mixed_report.get("reportPath") or "")),
                    ),
                ),
                "runs": [
                    {
                        "runtime": run.get("runtime"),
                        "returnCode": run.get("returnCode"),
                        "elapsedMs": run.get("elapsedMs"),
                        "summary": run.get("summary"),
                    }
                    for run in runs
                ],
            }
        else:
            run = _run_verifier_once(root, runtime, runtime_timeout=runtime_timeout, with_browser=with_browser, extra_env=extra_env)
            result = {
                "schema": PROOF_RUN_SCHEMA,
                "runtime": runtime,
                "status": run["summary"].get("status") or "unknown",
                "ok": bool(run.get("ok")) or bool(run["summary"].get("realRuntimeOutput")),
                "alreadyRunning": False,
                "lock": lock,
                "returnCode": run.get("returnCode"),
                "elapsedMs": run.get("elapsedMs"),
                "report": run.get("report"),
                "summary": run.get("summary"),
                "stdoutPreview": run.get("stdoutPreview"),
                "stderrPreview": run.get("stderrPreview"),
            }
    finally:
        _release_proof_run_lock(root, lock)
    result["proofStatus"] = build_real_agent_proof_status(root)
    return result
