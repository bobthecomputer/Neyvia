"""Fail-closed bridge to Laya's named local computer-use workflows."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .durability import atomic_write_json


LAYA_BASE_URL = "http://127.0.0.1:8793"
NEYVIA_WORKFLOW = "neyvia_desktop_navigation"
NEYVIA_GOAL = "Open Neyvia and navigate to the Agent Live surface."
MAX_RESPONSE_BYTES = 1_000_000


def _post(route: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(LAYA_BASE_URL + route,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(f"Laya local service unavailable: {type(exc).__name__}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Laya response exceeded the bounded receipt size")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Laya returned a malformed JSON receipt") from exc
    if not isinstance(value, dict):
        raise ValueError("Laya returned a non-object receipt")
    return value


def _receipt_passed(value: dict[str, Any]) -> bool:
    worker = value.get("worker_receipt")
    if not isinstance(worker, dict):
        return False
    window = worker.get("window")
    trace = worker.get("trace")
    if (value.get("format") != "laya-native-computer-run-v1"
            or value.get("status") != "completed"
            or value.get("reason") != "postcondition_verified"
            or value.get("execution_performed") is not True
            or value.get("outcome_unknown") is not False
            or value.get("provider_id") != "luna-uia-background-host"
            or worker.get("format") != "laya-luna-neyvia-desktop-v1"
            or worker.get("passed") is not True
            or worker.get("execution_performed") is not True
            or not isinstance(window, dict) or type(window.get("pid")) is not int or window["pid"] <= 0
            or not isinstance(trace, list) or not trace):
        return False
    if (not isinstance(trace[0], dict) or not isinstance(trace[-1], dict)
            or worker.get("initial_page") != trace[0].get("from")
            or worker.get("final_page") != trace[-1].get("to")):
        return False
    for step in trace:
        if not isinstance(step, dict) or step.get("after_page") != step.get("to"):
            return False
        digest = step.get("before_hash")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return False
    return True


class LayaComputerUse:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def capabilities(self) -> dict[str, Any]:
        try:
            value = _post("/v1/computer-use/native/capabilities", {}, timeout=8)
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "status": "blocked", "provider": "laya",
                    "reason": str(exc), "callableWorkflows": []}
        supported = value.get("supported_workflows")
        supported = supported if isinstance(supported, list) else []
        ready = (value.get("format") == "laya-native-computer-capabilities-v1"
                 and value.get("provider_attached") is True
                 and value.get("execution_enabled") is True
                 and NEYVIA_WORKFLOW in supported)
        return {"ok": ready, "status": "ready" if ready else "blocked",
                "provider": "laya", "providerId": value.get("provider_id"),
                "providerVersion": value.get("provider_version"),
                "callableWorkflows": [NEYVIA_WORKFLOW] if ready else [],
                "reportedWorkflows": supported,
                "genericNativeAppCoverage": value.get("generic_native_app_coverage") is True,
                "reason": "" if ready else str(value.get("blocker") or "Named Neyvia workflow unavailable"),
                "boundary": "Capability status is a preflight; only a completed run receipt proves this installed-app journey."}

    def run_neyvia_navigation(self) -> dict[str, Any]:
        capability = self.capabilities()
        if not capability["ok"]:
            return {"ok": False, "status": "blocked", "provider": "laya",
                    "reason": capability["reason"], "message": capability["reason"],
                    "executionPerformed": False}
        try:
            value = _post("/v1/computer-use/native/run",
                {"workflow": NEYVIA_WORKFLOW, "goal": NEYVIA_GOAL}, timeout=180)
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "status": "action_uncertain", "provider": "laya",
                    "reason": str(exc), "message": str(exc), "executionPerformed": None,
                    "boundary": "The request may have reached Laya; inspect its provider state before retrying."}
        accepted = _receipt_passed(value)
        try:
            from .laya_ledger import record
            record(self.root, task="computer-use", path="laya.native.neyvia_navigation", decision=NEYVIA_WORKFLOW,
                   outcome="answered" if accepted else "escalated", latency_ms=0,
                   detail="" if accepted else str(value.get("reason") or value.get("status") or "")[:120],
                   modelCalls=(value.get("worker_receipt") or {}).get("model_calls") if isinstance(value.get("worker_receipt"), dict) else None)
        except Exception:
            pass
        run_id = str(value.get("run_id") or "")
        receipt_hash = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        artifact = self.root / ".agent_control" / "laya_runs" / f"{receipt_hash[:24]}.json"
        atomic_write_json(artifact, value)
        worker = value.get("worker_receipt") if isinstance(value.get("worker_receipt"), dict) else {}
        uncertain = not accepted and (value.get("outcome_unknown") is True
            or value.get("execution_performed") is True or worker.get("execution_performed") is True)
        detail = str(worker.get("message") or value.get("error") or "")[:240]
        return {"ok": accepted, "status": "completed" if accepted else ("action_uncertain" if uncertain else "blocked"),
                "provider": "laya", "workflow": NEYVIA_WORKFLOW,
                "runId": run_id, "providerReceiptSha256": receipt_hash,
                "receiptFileSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "layaReceiptHash": value.get("receipt_hash"),
                "providerStatus": value.get("status"), "providerReason": value.get("reason"),
                "providerDetail": detail,
                "message": "" if accepted else f"Laya {value.get('status') or 'blocked'}: {detail or value.get('reason') or 'receipt did not pass'}",
                "executionPerformed": value.get("execution_performed"),
                "outcomeUnknown": value.get("outcome_unknown"),
                "windowPid": (worker.get("window") or {}).get("pid") if isinstance(worker.get("window"), dict) else None,
                "verifiedTransitions": len(worker.get("trace") or []) if accepted else 0,
                "selectionModelCalls": worker.get("model_calls"),
                "providerReceiptPath": str(artifact), "artifacts": [str(artifact)],
                "boundary": ("Verified installed Neyvia desktop navigation only; local source changes and generic computer use are not proved."
                    if accepted else "No desktop journey verified; inspect the provider receipt before retrying an uncertain action.")}


__all__ = ["LayaComputerUse", "NEYVIA_WORKFLOW"]
