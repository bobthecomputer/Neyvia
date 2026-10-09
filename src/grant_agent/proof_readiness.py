"""Startup readiness runs only the changed Connected Language contracts.

The durable receipt states the impact scope. Startup never launches the old
complete suite or tour; release admission also needs build and LAYA outcomes.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MAX_FAILURES = 25


def _path(root):
    return Path(root) / ".agent_control/proofs/readiness.json"


def _write(root, payload):
    from .durability import atomic_write_json
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def failing_claims(report):
    """The failing claims in a verification report, bounded and text-only."""
    rows = []
    for area in report.get("areas", []):
        if area.get("ok"):
            continue
        detail = [f"{c.get('id')}: {c.get('error')}" for c in area.get("failures") or [] if not c.get("ok", True)]
        fallback = (area.get("error") or area.get("reason") or "failed").strip().splitlines()[-1]
        rows.append({"claim": area.get("area"), "error": (detail[0] if detail else fallback)[:300], "count": max(1, len(detail))})
    for row in report.get("manualSelfChecks", []):
        if row.get("status") == "failed":
            rows.append({"claim": f"{row.get('manual')}/{row.get('chapter')}/{row.get('id')}", "error": str(row.get("error"))[:300], "count": 1})
    return rows[:MAX_FAILURES]


def skipped_claims(report):
    """Manual rows excluded from the self-check scope, each with its stated reason.

    Skipped is neither passed nor failed: the claim is verified outside this
    self-check, so readiness lists it rather than letting it read as covered.
    """
    rows = [{"claim": f"{row.get('manual')}/{row.get('chapter')}/{row.get('id')}", "reason": str(row.get("reason"))[:300]}
            for row in report.get("manualSelfChecks", []) if row.get("status") == "skipped"]
    # Area contracts whose prepared prerequisite is absent: in scope, unexercised.
    rows += [{"claim": f"{row.get('area')}/{row.get('contract')}", "reason": str(row.get("reason"))[:300]}
             for row in report.get("skippedContracts") or []]
    return rows[:MAX_FAILURES]


def status(root):
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "unknown", "reason": "No self-check has been started on this workspace"}
    if data.get("state") == "running" and data.get("pid") != os.getpid():
        # A previous backend died mid-run; do not claim it is still running.
        return {**data, "state": "unknown", "reason": "The backend that started this self-check is no longer running"}
    return data


def _count(value):
    return len(value) if isinstance(value, list) else value


def run_now(root, *, timeout_seconds=55.0, low_priority=True, since=None):
    """Check the diff since the last passing contract check, with explicit scope."""
    started = time.time()
    previous = status(root)
    since = since or os.environ.get("NEYVIA_PROOF_SINCE") or previous.get("checkedCommit") or "HEAD^"
    _write(root, {"state": "running", "startedAt": started, "pid": os.getpid()})
    try:
        from .contract_gate import run
        report = run(since, timeout=timeout_seconds, build=False)
        failures = [{"claim": row["step"], "error": row.get('reason') or "Outcome check failed; inspect " + row.get("logs",''), "count": 1}
                    for row in report["steps"] if not row["ok"]]
        failures += [{"claim": path, "error": "Changed file has no outcome contract", "count": 1} for path in report["uncovered"]]
        result = {"state": "passed" if report["contractsOk"] else "failed", "contractsOk": report["contractsOk"],
                  "complete": report["contractsOk"], "scope": "impact", "since": report["since"],
                  "selectedContracts": report["selectedContracts"], "uncovered": report["uncovered"],
                  "failures": failures[:MAX_FAILURES], "failureCount": len(failures),
                  "blocked": len(report["unboundContracts"]), "skipped": [], "releaseGate": False}
        if report["contractsOk"]:
            result["checkedCommit"] = report["commit"]
        elif previous.get("checkedCommit"):
            result["checkedCommit"] = previous["checkedCommit"]
    except Exception as exc:  # noqa: BLE001 - the receipt must say why, never raise into the backend
        result = {"state": "error", "error": str(exc)[-1500:], "failures": []}
    result.update(startedAt=started, finishedAt=time.time(), durationMs=int((time.time() - started) * 1000), pid=os.getpid())
    _write(root, result)
    return result


def start_background(root, **options):
    thread = threading.Thread(target=run_now, args=(root,), kwargs=options, name="neyvia-proof-self-check", daemon=True)
    thread.start()
    return thread
