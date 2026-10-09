from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .subprocess_utils import hidden_windows_subprocess_kwargs
from .proofs_e_sv import enforced


SUPPORT_BUNDLE_SCHEMA = "neyvia.support_bundle.v1"
SUPPORT_REDACTION_SCHEMA = "neyvia.support_redaction_policy.v1"
DEFAULT_MAX_JOBS = 12
MAX_MAX_JOBS = 50
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_LOG_INSPECTION_BYTES = 2 * 1024 * 1024

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:+-]{1,160}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_ERROR_TYPE_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Timeout|Failure))\b"
)
_SECRET_RESIDUAL_RE = re.compile(
    r"(?i)(Bearer\s+\S+|github_pat_[A-Za-z0-9_]+|\bgh[pousr]_[A-Za-z0-9_]+|"
    r"\bsk-[A-Za-z0-9_-]{8,}|\bAKIA[0-9A-Z]{8,}|"
    r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|"
    r"credential|private[_-]?key|client[_-]?secret|refresh[_-]?token)\s*[=:]\s*\S+)"
)
_FORBIDDEN_RAW_JSON_KEYS = (
    '"prompt"',
    '"promptPreview"',
    '"request"',
    '"workspacePath"',
    '"workerCommand"',
    '"logPath"',
    '"environment"',
    '"remoteUrl"',
)

_ID_FIELDS = (
    "id",
    "status",
    "mode",
    "harnessId",
    "runtime",
    "cancelReason",
    "cancelOutcome",
    "stopReason",
    "budgetOutcome",
)
_TIME_FIELDS = (
    "createdAt",
    "startedAt",
    "updatedAt",
    "finishedAt",
    "blockedAt",
    "interruptedAt",
    "cancelRequestedAt",
    "cancelledAt",
    "budgetExhaustedAt",
    "budgetEnforcedAt",
)
_BUDGET_NUMBER_FIELDS = (
    "maxRuntimeSeconds",
    "remainingRuntimeSecondsAtArm",
    "remainingRuntimeSecondsAtFinish",
)
_BUDGET_TIME_FIELDS = ("startedAt", "finishedAt", "releasedAt", "exhaustedAt")
_ADMISSION_NUMBER_FIELDS = ("maxOpenJobs", "openJobsBefore", "availableSlotsBefore")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: object, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not _IDENTIFIER_RE.fullmatch(text):
        return "<REDACTED_IDENTIFIER>"
    return text


def _safe_timestamp(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "<INVALID_TIMESTAMP>"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _safe_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        if path.is_symlink():
            return None, "symlink"
        if path.stat().st_nlink > 1:
            return None, "hardlink"
        if path.stat().st_size > MAX_RECEIPT_BYTES:
            return None, "oversized"
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "io-error"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except json.JSONDecodeError:
        return None, "invalid-json"
    except OSError:
        return None, "io-error"
    if not isinstance(raw, dict):
        return None, "not-object"
    return raw, "available"


def _safe_job(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "schema": _safe_identifier(payload.get("schema"), fallback="unknown"),
    }
    for field in _ID_FIELDS:
        value = payload.get(field)
        if value is not None and str(value).strip():
            safe[field] = _safe_identifier(value, fallback="unknown")
    for field in _TIME_FIELDS:
        value = _safe_timestamp(payload.get(field))
        if value is not None:
            safe[field] = value

    error_text = str(payload.get("error") or "")
    safe["errorPresent"] = bool(error_text)
    if error_text:
        safe["errorSha256"] = hashlib.sha256(
            error_text.encode("utf-8", errors="replace")
        ).hexdigest()
        error_match = _ERROR_TYPE_RE.search(error_text)
        if error_match:
            safe["errorType"] = _safe_identifier(error_match.group(1).split(".")[-1])

    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        metric_summary: dict[str, Any] = {}
        for field in (
            "queueLatencyMs",
            "executionDurationMs",
            "totalDurationMs",
            "timelinePhaseCount",
        ):
            value = _safe_number(metrics.get(field))
            if value is not None:
                metric_summary[field] = value
        for field in ("receiptPresent", "terminal"):
            value = metrics.get(field)
            if isinstance(value, bool):
                metric_summary[field] = value
        if metric_summary:
            safe["metrics"] = metric_summary

    budget = payload.get("budget")
    if isinstance(budget, dict):
        budget_summary: dict[str, Any] = {}
        value = budget.get("status")
        if value is not None and str(value).strip():
            budget_summary["status"] = _safe_identifier(value)
        if isinstance(budget.get("hard"), bool):
            budget_summary["hard"] = budget["hard"]
        for field in _BUDGET_NUMBER_FIELDS:
            value = _safe_number(budget.get(field))
            if value is not None:
                budget_summary[field] = value
        for field in _BUDGET_TIME_FIELDS:
            value = _safe_timestamp(budget.get(field))
            if value is not None:
                budget_summary[field] = value
        if budget_summary:
            safe["budget"] = budget_summary

    admission = payload.get("admission")
    if isinstance(admission, dict):
        admission_summary: dict[str, Any] = {}
        policy = admission.get("policy")
        if policy is not None and str(policy).strip():
            admission_summary["policy"] = _safe_identifier(policy)
        for field in _ADMISSION_NUMBER_FIELDS:
            value = _safe_number(admission.get(field))
            if value is not None:
                admission_summary[field] = value
        admitted_at = _safe_timestamp(admission.get("admittedAt"))
        if admitted_at is not None:
            admission_summary["admittedAt"] = admitted_at
        if admission_summary:
            safe["admission"] = admission_summary

    result = payload.get("result")
    if isinstance(result, dict):
        result_summary: dict[str, Any] = {}
        for field in ("status", "blockedReason", "providerId", "providerStatus"):
            value = result.get(field)
            if value is not None and str(value).strip():
                result_summary[field] = _safe_identifier(value)
        if result_summary:
            safe["resultSummary"] = result_summary
    return safe


def _safe_admission_policy(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    safe: dict[str, Any] = {}
    for field in ("schema", "mode"):
        value = payload.get(field)
        if value is not None and str(value).strip():
            safe[field] = _safe_identifier(value)
    for field in ("maxOpenJobs", "previousMaxOpenJobs"):
        value = _safe_number(payload.get(field))
        if value is not None:
            safe[field] = value
    for field in ("createdAt", "updatedAt", "tightenedAt"):
        value = _safe_timestamp(payload.get(field))
        if value is not None:
            safe[field] = value
    return safe or None


def _bounded_log_sample(path: Path, size: int) -> tuple[bytes, bool]:
    if size <= MAX_LOG_INSPECTION_BYTES:
        with path.open("rb") as handle:
            return handle.read(MAX_LOG_INSPECTION_BYTES + 1), False
    half = MAX_LOG_INSPECTION_BYTES // 2
    with path.open("rb") as handle:
        prefix = handle.read(half)
        handle.seek(max(0, size - half))
        suffix = handle.read(half)
    return prefix + suffix, True


def _log_index(log_path: Path, job_id: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "jobId": _safe_identifier(job_id, fallback="unknown"),
        "present": False,
        "rawContentIncluded": False,
    }
    try:
        if log_path.is_symlink():
            row["refusedSymlink"] = True
            return row
    except OSError:
        row["inspectionState"] = "io-error"
        return row
    if not log_path.is_file():
        return row
    row["present"] = True
    try:
        stat = log_path.stat()
        if stat.st_nlink > 1:
            row.update(present=False, refusedHardlink=True)
            return row
        size = int(stat.st_size)
        row["bytes"] = size
        row["modifiedAtNs"] = int(stat.st_mtime_ns)
        sample, truncated = _bounded_log_sample(log_path, size)
        row["inspectedBytes"] = len(sample)
        row["inspectionTruncated"] = truncated
        digest = hashlib.sha256(sample).hexdigest()
        if truncated:
            row["sampleSha256"] = digest
            row["sampleScope"] = "first-and-last-bounded-bytes"
        else:
            row["sha256"] = digest
        text = sample.decode("utf-8", errors="replace")
        sampled_line_count = len(text.splitlines())
        if truncated:
            row["sampleLineCount"] = sampled_line_count
        else:
            row["lineCount"] = sampled_line_count
        error_types: Counter[str] = Counter()
        for match in _ERROR_TYPE_RE.finditer(text):
            error_type = _safe_identifier(match.group(1).split(".")[-1])
            if error_type and error_type != "<REDACTED_IDENTIFIER>":
                error_types[error_type] += 1
        row["errorTypeCounts"] = dict(sorted(error_types.items()))
    except OSError:
        row["inspectionState"] = "io-error"
    return row


def _git_head(root: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
            **hidden_windows_subprocess_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False}
    head = completed.stdout.strip()
    if completed.returncode != 0 or not _SHA_RE.fullmatch(head):
        return {"available": False}
    return {"available": True, "headSha": head.lower()}


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in ("neyvia-runtime", "grant-agent-harness"):
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
        safe_version = _safe_identifier(version)
        if safe_version != "<REDACTED_IDENTIFIER>":
            versions[distribution] = safe_version
    return versions


def _runtime_snapshot(root: Path) -> dict[str, Any]:
    return {
        "python": {
            "implementation": _safe_identifier(
                platform.python_implementation(), fallback="unknown"
            ),
            "version": _safe_identifier(platform.python_version(), fallback="unknown"),
            "executableName": _safe_identifier(
                Path(sys.executable).name, fallback="python"
            ),
        },
        "platform": {
            "system": _safe_identifier(platform.system(), fallback="unknown"),
            "release": _safe_identifier(platform.release(), fallback="unknown"),
            "machine": _safe_identifier(platform.machine(), fallback="unknown"),
        },
        "packages": _package_versions(),
        "git": _git_head(root),
    }


def _resolve_jobs_root(root: Path) -> tuple[Path, Path | None, str]:
    control_root = root / ".agent_control"
    jobs_root = control_root / "harness_jobs"
    try:
        if control_root.is_symlink() or jobs_root.is_symlink():
            return jobs_root, None, "refused-symlink"
        resolved = jobs_root.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return jobs_root, None, "refused-outside-workspace"
    if not jobs_root.is_dir():
        return jobs_root, resolved, "missing"
    return jobs_root, resolved, "available"


def _collect_harness_evidence(
    root: Path,
    *,
    max_jobs: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    jobs_root, jobs_root_resolved, jobs_root_state = _resolve_jobs_root(root)
    policy_path = jobs_root / ".harness-job-admission-policy.json"
    if jobs_root_state == "available":
        policy_raw, policy_state = _read_json(policy_path)
        paths = list(jobs_root.glob("harness-job-*.json"))
    else:
        policy_raw = None
        policy_state = jobs_root_state if jobs_root_state != "missing" else "missing"
        paths = []
    policy = _safe_admission_policy(policy_raw)

    def sort_key(path: Path) -> int:
        try:
            return int(path.lstat().st_mtime_ns)
        except OSError:
            return 0

    job_paths = sorted(paths, key=sort_key, reverse=True)
    selected = job_paths[:max_jobs]
    rows: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    unreadable = 0
    resolved_root = jobs_root_resolved or jobs_root

    for path in selected:
        payload, read_state = _read_json(path)
        if payload is None:
            unreadable += 1
            statuses["unreadable"] += 1
            rows.append(
                {
                    "id": _safe_identifier(path.stem, fallback="unknown"),
                    "schema": "unreadable",
                    "status": "unreadable",
                    "readState": _safe_identifier(read_state, fallback="unreadable"),
                }
            )
            canonical_log = jobs_root / f"{path.stem}.log"
            log_rows.append(_log_index(canonical_log, path.stem))
            continue

        safe = _safe_job(payload)
        status = _safe_identifier(payload.get("status"), fallback="unknown")
        if status == "<REDACTED_IDENTIFIER>":
            status = "unknown"
        statuses[status] += 1
        rows.append(safe)

        job_id = str(payload.get("id") or path.stem)
        declared_log_text = str(payload.get("logPath") or "").strip()
        log_path = jobs_root / f"{path.stem}.log"
        if declared_log_text:
            declared_log = Path(declared_log_text)
            candidate = (
                declared_log if declared_log.is_absolute() else jobs_root / declared_log
            )
            try:
                candidate_resolved = candidate.resolve(strict=False)
                candidate_resolved.relative_to(resolved_root)
            except (OSError, ValueError):
                candidate_resolved = log_path
            log_path = candidate if candidate.is_symlink() else candidate_resolved
        log_rows.append(_log_index(log_path, job_id))

    health = {
        "jobsRootPresent": jobs_root_state == "available",
        "jobsRootState": _safe_identifier(jobs_root_state, fallback="missing"),
        "selectedJobCount": len(selected),
        "totalReceiptCount": len(job_paths),
        "unreadableSelectedJobs": unreadable,
        "statusCounts": dict(sorted(statuses.items())),
        "admissionPolicy": policy,
        "admissionPolicyState": (
            "available"
            if policy is not None and policy_state == "available"
            else _safe_identifier(policy_state, fallback="missing")
        ),
    }
    return {"health": health, "jobs": rows}, log_rows


def _redaction_policy() -> dict[str, Any]:
    return {
        "schema": SUPPORT_REDACTION_SCHEMA,
        "strategy": "allowlist-first-data-minimization",
        "excluded": [
            "raw prompts and prompt previews",
            "raw job requests",
            "raw provider or agent results",
            "raw log content",
            "free-form error text",
            "workspace paths",
            "worker command lines",
            "environment values",
            "remote URLs",
            "credentials and authentication material",
        ],
        "includedLogEvidence": [
            "presence",
            "byte count",
            "full SHA-256 and line count for bounded logs",
            "bounded first/last sample SHA-256 and sampled line count for large logs",
            "exception-type counts from inspected bytes",
        ],
        "note": (
            "Raw agent/provider logs are deliberately excluded. Post-hoc regex scrubbing "
            "cannot prove that arbitrary project text is unrelated or safe to disclose, "
            "so the bundle keeps only bounded diagnostic metadata and hashes."
        ),
    }


def _assert_bundle_safe(files: dict[str, bytes]) -> None:
    for name, data in files.items():
        text = data.decode("utf-8", errors="replace")
        for forbidden_key in _FORBIDDEN_RAW_JSON_KEYS:
            if forbidden_key in text:
                raise RuntimeError(
                    f"Support bundle safety gate rejected {name}: raw field "
                    f"{forbidden_key} remained."
                )
        if _SECRET_RESIDUAL_RE.search(text):
            raise RuntimeError(
                f"Support bundle safety gate rejected {name}: secret-like content remained."
            )


@enforced("sv.support.bundle")
def build_redacted_support_bundle(
    root: Path,
    output: Path,
    *,
    max_jobs: int = DEFAULT_MAX_JOBS,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = Path(root).expanduser().resolve(strict=True)
    output = Path(output).expanduser()
    if max_jobs < 1 or max_jobs > MAX_MAX_JOBS:
        raise ValueError(f"max_jobs must be between 1 and {MAX_MAX_JOBS}.")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Support bundle already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    harness_payload, log_rows = _collect_harness_evidence(root, max_jobs=max_jobs)
    created_at = _utc_now()
    bundle_id = f"support-{uuid.uuid4().hex}"
    manifest = {
        "schema": SUPPORT_BUNDLE_SCHEMA,
        "bundleId": bundle_id,
        "createdAt": created_at,
        "workspaceToken": f"workspace-{uuid.uuid4().hex}",
        "purpose": "redacted Neyvia support and diagnosis evidence",
        "files": [
            "manifest.json",
            "runtime.json",
            "harness-jobs.json",
            "logs/index.json",
            "redaction-policy.json",
        ],
        "rawProjectContentIncluded": False,
        "rawCredentialsIncluded": False,
    }
    files = {
        "manifest.json": _json_bytes(manifest),
        "runtime.json": _json_bytes(_runtime_snapshot(root)),
        "harness-jobs.json": _json_bytes(harness_payload),
        "logs/index.json": _json_bytes({"logs": log_rows}),
        "redaction-policy.json": _json_bytes(_redaction_policy()),
    }
    _assert_bundle_safe(files)
    from .proofs_e_sv import check_support_payload
    check_support_payload(files, max_jobs)

    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            now_tuple = datetime.now().timetuple()[:6]
            for name, data in files.items():
                info = zipfile.ZipInfo(name)
                info.date_time = now_tuple
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, data)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(output)
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "schema": SUPPORT_BUNDLE_SCHEMA,
        "bundleId": bundle_id,
        "createdAt": created_at,
        "output": str(output.resolve()),
        "bytes": output.stat().st_size,
        "sha256": _sha256_file(output),
        "includedFiles": list(files),
        "selectedHarnessJobs": harness_payload["health"]["selectedJobCount"],
        "rawProjectContentIncluded": False,
        "rawCredentialsIncluded": False,
        "safetyGate": "passed",
    }
