"""Durable, authority-bound operations with observable verification.

This module is deliberately an adapter seam: native tool hosts can supply an
authority decision, observations, and an effect without this layer knowing how
the underlying tool works.  A pending or uncertain record is never replayed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import ntpath
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
import inspect

from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False,
                                     default=str).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
        return value
    except (TypeError, ValueError):
        return {"repr": repr(value)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _comparison_path(path: Path) -> str:
    """Canonical comparison spelling after resolving the filesystem path."""
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def _inside_root(path: Path, root: Path) -> bool:
    """Check path containment without prefix-string tests or Windows syntax mismatch."""
    if os.name == "nt":
        try:
            common = ntpath.commonpath((_comparison_path(root), _comparison_path(path)))
        except ValueError:  # different drives or incompatible path forms
            return False
        return ntpath.normcase(common) == _comparison_path(root)
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_error(exc: BaseException) -> str:
    value = " ".join(str(exc).split())[:1000]
    value = re.sub(
        r"(?i)(\b(?:api[-_ ]?key|authorization|credential|password|private[-_ ]?key|secret|token|cookie)\b\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    return value or type(exc).__name__


def _artifact_checks(value: Any, root: Path) -> list[dict[str, Any]]:
    """Validate declared artifact hashes; an absent artifact is never proof."""
    if not value:
        return []
    rows = value if isinstance(value, list) else [value]
    checked: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            raise ValueError("artifact declarations must be objects or paths")
        raw_path = str(item.get("path") or item.get("artifact") or "").strip()
        if not raw_path:
            raise ValueError("artifact path is required")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not _inside_root(path, root.resolve()):
            exc = ValueError("path escapes workspace root")
            raise ValueError("artifact must remain inside workspace root") from exc
        if not path.is_file():
            raise ValueError(f"artifact is unavailable: {raw_path}")
        actual = _sha256(path)
        expected = str(item.get("sha256") or "").strip().lower()
        if expected and expected != actual:
            raise ValueError(f"artifact sha256 mismatch for {raw_path}")
        checked.append({"path": str(path), "sha256": actual,
                        "declaredSha256": expected or None,
                        "sizeBytes": path.stat().st_size})
    return checked


def _call(callback: Any, context: dict[str, Any]) -> Any:
    if callback is None:
        return None
    if not callable(callback):
        return callback
    # Bind first so a TypeError raised *inside* a mutation is never mistaken
    # for a zero-argument callback (which could execute the mutation twice).
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(context)
    if len(signature.parameters) == 0:
        return callback()
    return callback(context)


def _authority_ok(authority: Any) -> tuple[bool, str]:
    if authority is None:
        return False, "authority is required"
    if callable(authority):
        authority = _call(authority, {})
    if authority is True:
        return True, ""
    if not isinstance(authority, dict):
        return False, "authority decision is not structured"
    granted = authority.get("granted", authority.get("allowed", authority.get("authorized")))
    if granted is not True:
        return False, str(authority.get("reason") or "authority was not granted")
    return True, ""


class VerifiedOperationStore:
    """Persist one operation identity and its evidence under a stable scope."""

    schema = "neyvia.verified_operation.v1"

    def __init__(self, root: str | Path, scope: str = "default"):
        self.root = Path(root).resolve()
        if not str(scope).strip():
            raise ValueError("scope is required")
        base = self.root / ".agent_control" / "verified_operations" / _digest(scope)
        base.mkdir(parents=True, exist_ok=True)
        self.base = base

    def _path(self, operation_id: str) -> Path:
        operation_id = str(operation_id or "").strip()
        if not operation_id or len(operation_id) > 160:
            raise ValueError("operationId must contain 1-160 characters")
        return self.base / f"{_digest(operation_id)}.json"

    def inspect(self, operation_id: str) -> dict[str, Any]:
        path = self._path(operation_id)
        if not path.exists():
            return {"operationId": operation_id, "status": "not_started"}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != self.schema \
                or value.get("operationId") != operation_id \
                or value.get("status") not in {"pending", "verified", "failed", "unverified", "uncertain"}:
            raise ValueError("operation record is invalid; reconcile evidence before retrying")
        if value.get("status") in {"verified", "failed", "unverified"}:
            result = value.get("result")
            if not isinstance(result, dict) or _digest(result) != value.get("resultHash"):
                raise ValueError("operation result hash mismatch; reconcile its evidence before retrying")
        return value

    def list(self, *, limit: int = 50) -> dict[str, Any]:
        rows = []
        for path in sorted(self.base.glob("*.json"))[:max(1, min(int(limit), 100))]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                rows.append({k: item.get(k) for k in ("operationId", "toolId", "status", "startedAt", "finishedAt", "recoveryRef")})
            except (OSError, ValueError):
                rows.append({"status": "unreadable", "path": str(path)})
        return {"operations": rows, "scope": "verified operations"}

    def execute(self, operation_id: str, tool_id: str, *, authority: Any,
                preconditions: Iterable[Any] | None = None,
                before: Any = None, effect: Callable[..., Any] | None = None,
                after: Any = None, verify: Any = None,
                recovery_ref: Any = None, artifacts: Any = None,
                metadata: dict[str, Any] | None = None,
                request: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self._path(operation_id)
        # The operation ID is the caller's stable intent key.  Callback
        # identities, authority tokens, and observations are runtime details;
        # including them would turn a legitimate process restart into a false
        # conflict.  The tool identity remains bound to prevent relabelling.
        request_hash = _digest({"toolId": tool_id, "request": request or {}})
        with _exclusive_job_lock(path):
            granted, reason = _authority_ok(authority)
            if not granted:
                return {"ok": False, "status": "authority_required", "operationId": operation_id, "reason": reason}
            prior = self.inspect(operation_id)
            if prior["status"] != "not_started":
                if prior.get("requestHash") != request_hash:
                    return {"ok": False, "status": "operation_conflict", "operationId": operation_id}
                if prior["status"] in {"pending", "uncertain"}:
                    return {"ok": False, "status": "unknown_side_effects", "operationId": operation_id,
                            "recoveryRef": prior.get("recoveryRef"),
                            "message": "Prior execution may have changed state; recovery is required before retry."}
                return {**prior.get("result", {}), "ok": prior["status"] == "verified",
                        "status": "duplicate_suppressed", "operationId": operation_id,
                        "duplicateSuppressed": True, "operationReceiptPath": str(path)}

            context = {"operationId": operation_id, "toolId": tool_id, "root": str(self.root)}
            before_value = _jsonable(_call(before, context))
            failures = []
            for precondition in preconditions or ():
                result = _call(precondition, {**context, "before": before_value})
                if isinstance(result, dict):
                    passed = result.get("ok", result.get("satisfied", result.get("passed"))) is True
                    detail = result
                else:
                    passed, detail = bool(result), result
                if not passed:
                    failures.append(_jsonable(detail))
            if failures:
                return {"ok": False, "status": "precondition_failed", "operationId": operation_id,
                        "before": before_value, "failures": failures}
            record = {"schema": self.schema, "operationId": operation_id, "toolId": str(tool_id),
                      "requestHash": request_hash, "status": "pending", "startedAt": _now(),
                      "authority": _jsonable(authority), "before": before_value,
                      "recoveryRef": _jsonable(recovery_ref)}
            atomic_write_json(path, record)
            try:
                effect_result = _jsonable(_call(effect, {**context, "before": before_value}))
                after_value = _jsonable(_call(after, {**context, "before": before_value, "effect": effect_result}))
                checked = _artifact_checks(artifacts or (effect_result.get("artifacts") if isinstance(effect_result, dict) else None), self.root)
                verification = _jsonable(_call(verify, {**context, "before": before_value, "after": after_value, "effect": effect_result, "artifacts": checked}))
                verified = verification is True or (isinstance(verification, dict) and verification.get("verified") is True)
                effect_success = not (isinstance(effect_result, dict) and (
                    effect_result.get("ok") is False or str(effect_result.get("status") or "").lower() in {"failed", "error", "blocked", "uncertain"}))
                if verify is None:
                    verified = False
                    record_status = "unverified" if effect_success else "failed"
                    verification = {"verified": False, "reason": "verification callback is required"}
                else:
                    record_status = "verified" if verified and effect_success else "failed"
                    verified = verified and effect_success
                result = {"effect": effect_result, "after": after_value, "verification": verification, "artifacts": checked}
                record.update(status=record_status, result=result,
                              finishedAt=_now(), resultHash=_digest(result))
                atomic_write_json(path, record)
                return {"ok": verified, "status": record["status"], "operationId": operation_id,
                        "result": result, "operationReceiptPath": str(path)}
            except Exception as exc:
                record.update(status="uncertain", finishedAt=_now(), error=str(exc),
                              message="Effect outcome is unknown; automatic retry is prohibited.")
                atomic_write_json(path, record)
                return {"ok": False, "status": "unknown_side_effects", "operationId": operation_id,
                        "recoveryRef": _jsonable(recovery_ref), "operationReceiptPath": str(path),
                        "error": _safe_error(exc),
                        "message": record["message"]}


VerifiedOperations = VerifiedOperationStore
