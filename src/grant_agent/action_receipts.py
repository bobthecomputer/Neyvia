"""At-most-once native tool attempts with durable, inspectable outcomes.

An action ID identifies one intended mutation, not a retry attempt. This does not
make arbitrary shell commands idempotent or certify the resulting user outcome.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _safe_result(value: Any) -> dict[str, Any]:
    """Project callback output to durable, non-secret receipt metadata."""
    if not isinstance(value, dict):
        return {"ok": False, "status": "invalid_result"}
    allowed = {"ok", "status", "actionId", "duplicateSuppressed", "url", "finalUrl",
               "pageUrl", "origin", "hash", "sha256", "semanticHash", "revision",
               "observation", "actionReceiptPath", "operationStatus",
               "operationReceiptPath", "recoveryRef", "receipt_id", "receipt_path", "duration_ms"}
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"toolResult", "failure", "filesChanged", "verification"} and isinstance(item, (dict, list)):
            out[key] = _safe_tool_result(item)
            continue
        if key not in allowed:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            out[key] = item
    from .proofs_e_host import check_safe_receipt
    return check_safe_receipt(out)


def _safe_tool_result(value: Any, depth: int = 0) -> Any:
    """Keep structured semantic outcomes, excluding credential-bearing fields."""
    if depth > 16:
        return {"omitted": "depth_limit", "retrieval": "native receipt_path"}
    if isinstance(value, dict):
        return {str(key): _safe_tool_result(item, depth + 1) for key, item in value.items()
                if not re.search(r"password|secret|credential|authorization|cookie|api.?key|access.?token|refresh.?token", str(key), re.I)}
    if isinstance(value, list):
        return [_safe_tool_result(item, depth + 1) for item in value]
    return value


class NativeActionStore:
    def __init__(self, root: Path, scope: str):
        if not scope.strip():
            raise ValueError("A stable action scope is required")
        # Created on the first executed action: building a gateway (search,
        # describe, read-only sessions) must not write workspace state.
        self.base = Path(root) / ".agent_control" / "native_actions" / _digest(scope)

    def _path(self, action_id: str) -> Path:
        if not isinstance(action_id, str) or not action_id.strip() or len(action_id) > 160:
            raise ValueError("actionId must contain 1-160 characters and identify the same intent across retries")
        return self.base / (_digest(action_id) + ".json")

    def inspect(self, action_id: str) -> dict[str, Any]:
        path = self._path(action_id)
        if not path.exists():
            return {"actionId": action_id, "status": "not_started"}
        # Never fall back to an older snapshot: it could precede a side effect.
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("actionId") != action_id
                or value.get("schema") != "neyvia.native_action.v1"
                or value.get("status") not in {"pending", "completed", "uncertain"}
                or not isinstance(value.get("requestHash"), str)):
            raise ValueError("Action record is invalid; reconcile its evidence before retrying")
        return value

    def list(self, *, after: str = "", limit: int = 20) -> dict[str, Any]:
        """Recover action IDs after context loss without loading result bodies."""
        limit = max(1, min(int(limit), 50))
        paths = sorted(path for path in self.base.glob("*.json") if path.name > after)
        rows = []
        for path in paths[:limit]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                rows.append({key: value.get(key) for key in ("actionId", "toolId", "status", "startedAt", "finishedAt")})
            except (OSError, ValueError, AttributeError):
                rows.append({"status": "unreadable", "actionReceiptPath": str(path)})
        return {"actions": rows, "nextCursor": paths[limit - 1].name if len(paths) > limit else None,
                "scope": "native gateway actions only; does not cover arbitrary shell or other tool hosts"}

    def execute(self, action_id: str, tool_id: str, arguments: dict[str, Any], call: Callable[[], dict[str, Any]],
                *, preflight: Callable[[], None] | None = None) -> dict[str, Any]:
        path = self._path(action_id)
        request_hash = _digest({"tool": tool_id, "arguments": arguments})
        self.base.mkdir(parents=True, exist_ok=True)
        with _exclusive_job_lock(path):
            prior = self.inspect(action_id)
            if prior["status"] != "not_started":
                if prior.get("requestHash") != request_hash:
                    return {"ok": False, "status": "action_conflict", "actionId": action_id,
                            "message": "This actionId is already bound to different tool arguments. Inspect its receipt; do not relabel a retry as a new action."}
                if prior["status"] == "completed":
                    result_path = path.with_suffix(".result")
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                        if not isinstance(result, dict) or _digest(result) != prior.get("resultHash"):
                            raise ValueError("Saved result hash mismatch")
                    except (OSError, ValueError) as exc:
                        return {"ok": False, "status": "action_uncertain", "actionId": action_id,
                                "message": f"The prior action completed but its saved receipt is unavailable: {exc}. Reconcile; do not repeat it."}
                    safe = _safe_result(result)
                    output = {**safe, "actionId": action_id, "duplicateSuppressed": True,
                            "actionReceiptPath": str(path), "observation": "saved prior result; not a fresh state check"}
                    from .proofs_e_host import check_action_completion
                    check_action_completion(path, prior, output, True)
                    return output
                return {"ok": False, "status": "action_uncertain", "actionId": action_id,
                        "actionReceiptPath": str(path),
                        "message": "A prior attempt may have changed state. Inspect the action and target before a separately identified recovery action; automatic replay is prohibited."}
            # Preflight may only observe and validate. It runs under the action
            # lock before pending, so rejected preconditions are not uncertain effects.
            if preflight is not None:
                preflight()
            record = {"schema": "neyvia.native_action.v1", "actionId": action_id, "toolId": tool_id,
                      "requestHash": request_hash, "status": "pending",
                      "startedAt": datetime.now(timezone.utc).isoformat()}
            # Persist before invoking the handler. Process death leaves pending,
            # which blocks replay even if the result was never recorded.
            atomic_write_json(path, record)
            # Exceptions deliberately leave pending: a handler may have changed
            # state before throwing, so failure is not proof that replay is safe.
            result = _safe_result(call())
            atomic_write_json(path.with_suffix(".result"), result)
            record.update(status="completed" if result.get("ok") is True else "uncertain",
                          resultHash=_digest(result), finishedAt=datetime.now(timezone.utc).isoformat())
            atomic_write_json(path, record)
            output = {**result, "actionId": action_id, "duplicateSuppressed": False, "actionReceiptPath": str(path)}
            from .proofs_e_host import check_action_completion
            check_action_completion(path, record, output, False)
            return output
