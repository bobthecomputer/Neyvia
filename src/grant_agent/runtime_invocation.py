from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable


RUNTIME_INVOCATION_SCHEMA = "neyvia.runtime_invocation.v1"
RUNTIME_STATES = {
    "available",
    "setup_required",
    "ready",
    "active",
    "suspended",
    "blocked",
    "closed",
}
_LEDGER_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ledger_path(root: Path) -> Path:
    return root.resolve() / ".agent_control" / "runtime_invocations.json"


def _read_ledger(root: Path) -> dict[str, Any]:
    path = _ledger_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    rows = payload.get("invocations") if isinstance(payload, dict) else []
    return {
        "schema": RUNTIME_INVOCATION_SCHEMA,
        "invocations": rows if isinstance(rows, list) else [],
    }


def _write_ledger(root: Path, ledger: dict[str, Any]) -> None:
    path = _ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(ledger.get("invocations") or [])[-240:]
    payload = {
        "schema": RUNTIME_INVOCATION_SCHEMA,
        "updatedAt": _utc_now(),
        "invocations": rows,
    }
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"rawPrompt", "environment", "credentials"}
    }


class RuntimeInvocationService:
    def __init__(self, root: Path, runner: Callable[[dict[str, Any]], dict[str, Any]]):
        self.root = root.resolve()
        self.runner = runner

    def list(self, *, limit: int = 40) -> dict[str, Any]:
        with _LEDGER_LOCK:
            rows = _read_ledger(self.root)["invocations"]
        return {
            "schema": RUNTIME_INVOCATION_SCHEMA,
            "states": sorted(RUNTIME_STATES),
            "invocations": [_public_row(row) for row in rows[-max(1, min(limit, 120)):]],
        }

    def transition(self, invocation_id: str, state: str) -> dict[str, Any]:
        normalized = str(state or "").strip().lower()
        if normalized not in {"suspended", "closed"}:
            raise ValueError("Runtime sessions can only be suspended or closed directly.")
        with _LEDGER_LOCK:
            ledger = _read_ledger(self.root)
            row = next(
                (
                    item
                    for item in ledger["invocations"]
                    if str(item.get("invocationId")) == str(invocation_id)
                ),
                None,
            )
            if row is None:
                raise KeyError(f"Unknown runtime invocation: {invocation_id}")
            row["state"] = normalized
            row["updatedAt"] = _utc_now()
            _write_ledger(self.root, ledger)
        return _public_row(row)

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = str(payload.get("message") or payload.get("objective") or "").strip()
        if not prompt:
            raise ValueError("A runtime message is required.")
        runtime = str(
            payload.get("runtime") or payload.get("runtimeId") or "codex"
        ).strip().lower()
        invocation_id = str(payload.get("invocationId") or "").strip()
        resume_requested = bool(invocation_id)
        now = _utc_now()
        with _LEDGER_LOCK:
            ledger = _read_ledger(self.root)
            row = next(
                (
                    item
                    for item in ledger["invocations"]
                    if str(item.get("invocationId")) == invocation_id
                ),
                None,
            )
            if resume_requested and row is None:
                raise KeyError(f"Unknown runtime invocation: {invocation_id}")
            if row is not None and not bool(row.get("resumeCapability")):
                raise RuntimeError(
                    f"{runtime} did not report a stable resumable session identity."
                )
            if row is None:
                invocation_id = f"runtime_{uuid.uuid4().hex[:20]}"
                row = {
                    "schema": RUNTIME_INVOCATION_SCHEMA,
                    "invocationId": invocation_id,
                    "provider": str((payload.get("route") or {}).get("provider") or ""),
                    "runtime": runtime,
                    "model": str((payload.get("route") or {}).get("model") or ""),
                    "mode": str(payload.get("mode") or "chat"),
                    "purpose": str(payload.get("purpose") or "conversation"),
                    "scope": str(payload.get("workspacePath") or ""),
                    "parentConversationId": str(payload.get("conversationId") or ""),
                    "parentMissionId": str(payload.get("missionId") or ""),
                    "promptProfile": str(payload.get("promptProfile") or ""),
                    "providerSessionId": "",
                    "state": "ready",
                    "resumeCapability": False,
                    "streaming": {
                        "supported": False,
                        "active": False,
                        "detail": "This provider adapter returned a completed turn; live token streaming was not reported.",
                    },
                    "messages": [],
                    "changes": [],
                    "artifacts": [],
                    "receipts": [],
                    "failure": None,
                    "createdAt": now,
                    "updatedAt": now,
                }
                ledger["invocations"].append(row)
            row["state"] = "active"
            row["updatedAt"] = now
            _write_ledger(self.root, ledger)

        runner_payload = {
            **payload,
            "runtime": runtime,
            "sessionId": str(row.get("providerSessionId") or payload.get("sessionId") or invocation_id),
        }
        try:
            result = self.runner(runner_payload)
        except Exception as exc:
            result = {"status": "failed", "error": str(exc), "reply": ""}

        status = str(result.get("status") or "").strip().lower()
        failed = status in {"failed", "error", "timeout", "blocked"} or bool(result.get("error"))
        compartment = result.get("compartment") if isinstance(result.get("compartment"), dict) else {}
        provider_session_id = str(
            result.get("sessionId")
            or compartment.get("sessionId")
            or row.get("providerSessionId")
            or ""
        ).strip()
        reply = str(
            result.get("reply")
            or result.get("finalMessage")
            or result.get("message")
            or ""
        ).strip()
        receipt = compartment.get("turnReceipt") or result.get("turnReceipt")
        with _LEDGER_LOCK:
            ledger = _read_ledger(self.root)
            stored = next(
                item
                for item in ledger["invocations"]
                if str(item.get("invocationId")) == invocation_id
            )
            stored["state"] = "blocked" if failed else "closed"
            stored["providerSessionId"] = provider_session_id
            stored["resumeCapability"] = bool(
                provider_session_id
                and result.get("resumeSupported", compartment.get("resumeSupported", False))
            )
            stored["messages"] = list(stored.get("messages") or [])[-30:] + [
                {"role": "user", "content": prompt, "at": now},
                {
                    "role": "assistant",
                    "content": reply,
                    "at": _utc_now(),
                    "status": "failed" if failed else "completed",
                },
            ]
            stored["changes"] = list(
                result.get("filesChanged") or compartment.get("filesChanged") or []
            )
            stored["artifacts"] = list(result.get("artifacts") or [])
            stored["receipts"] = [
                item
                for item in [receipt]
                if item
            ]
            stored["failure"] = (
                {
                    "message": str(result.get("error") or "Runtime invocation failed."),
                    "status": status or "failed",
                }
                if failed
                else None
            )
            stored["updatedAt"] = _utc_now()
            _write_ledger(self.root, ledger)
        return {
            **result,
            "status": "blocked" if failed else "closed",
            "lifecycle": _public_row(stored),
            "invocationId": invocation_id,
            "resumeCapability": bool(stored.get("resumeCapability")),
        }
