"""Observed execution facts, without inferring a policy owner from error text."""
from __future__ import annotations
import json
from pathlib import Path
import statistics
import subprocess
import time


def failure_record(error, *, tool, phase, mutability):
    kind = "unknown"
    if phase == "availability":
        kind = "dependency_or_configuration"
    elif phase == "validation":
        kind = "invalid_arguments"
    elif isinstance(error, PermissionError):
        kind = "operating_system_access"
    elif isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        kind = "timeout"
    elif isinstance(error, (ModuleNotFoundError, FileNotFoundError)):
        kind = "missing_dependency_or_file"
    effect_possible = phase == "execution" and mutability not in {"read", "none"}
    return {"schema": "neyvia.execution_failure.v1", "tool": tool,
            "source": "native_tool_registry", "stage": phase, "kind": kind,
            "exceptionType": type(error).__name__ if error is not None else None,
            "message": str(error) if error is not None else "Tool reported failure",
            "policyOwner": None, "policyOwnerKnown": False,
            "sideEffects": "uncertain" if effect_possible else "no_mutation_established",
            "retrySafety": "requires_reconciliation" if effect_possible else "requires_changed_conditions",
            "automaticRetry": False,
            "nextAction": "Inspect effects and the saved operation before retrying" if effect_possible else "Inspect the reported cause and refresh capability evidence before retrying"}


def summarize_receipts(root, *, limit=200):
    """Bounded tool-level telemetry. Tool success does not prove user success."""
    limit = max(1, min(int(limit), 500))
    files = sorted((Path(root) / ".agent_control" / "tool_receipts").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    groups = {}
    invalid = 0
    for file in files[:limit]:
        try:
            if file.stat().st_size > 2097152:
                invalid += 1; continue
            row = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or row.get("schema") != "fluxio.native_tool_receipt.v1" or type(row.get("ok")) is not bool or not isinstance(row.get("tool"), str):
                invalid += 1; continue
            duration = row.get("duration_ms")
            if type(duration) not in {int, float} or not 0 <= duration < float("inf"):
                invalid += 1; continue
            group = groups.setdefault(row["tool"], {"tool": row["tool"], "calls": 0, "successfulCalls": 0, "durations": [], "latestReceipt": str(file), "latestFailure": None})
            group["calls"] += 1
            group["successfulCalls"] += int(row["ok"])
            group["durations"].append(duration)
            if not row["ok"] and group["latestFailure"] is None:
                group["latestFailure"] = row.get("failure") or {"kind": "unknown", "message": row.get("error", ""), "policyOwnerKnown": False}
        except (OSError, ValueError, KeyError, TypeError):
            invalid += 1
    result = []
    for group in groups.values():
        durations = group.pop("durations")
        group.update(medianDurationMs=statistics.median(durations), maximumDurationMs=max(durations))
        result.append(group)
    return {"schema": "neyvia.runtime_evidence.v1", "observedAt": time.time(), "tools": result,
            "omittedReceipts": max(0, len(files) - limit), "invalidReceipts": invalid,
            "measurementBoundary": "native tool receipts; not user outcomes", "tokenCost": None,
            "verifiedUserOutcomes": None, "costEvidenceAvailable": False}


def context_observation(root):
    path = Path(root) / ".agent_control" / "runtime_preflight" / "latest.json"
    try:
        if path.stat().st_size > 65536:
            raise ValueError("Oversized preflight")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "neyvia.runtime_preflight.v1":
            raise ValueError("Unexpected preflight schema")
        return {"status": "stale" if time.time() >= value["expiresAt"] else "configuration_observed",
                "observedAt": value["observedAt"], "executionVerified": False,
                "unavailableTools": [row["tool"] for row in value["tools"] if not row["configurationAvailable"]][:30],
                "retrievalTool": "runtime.preflight", "browserConnection": "not_observed"}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "not_checked", "executionVerified": False, "retrievalTool": "runtime.preflight"}


def completion_evidence(root):
    """Reconcile a saved checkpoint with current bytes, without endorsing its claims."""
    from .proof_capsules import sha256_file
    root = Path(root).resolve()
    checkpoint = root / "proof" / "semantic-primitives" / "operating-checkpoint.json"
    base = {"schema": "neyvia.completion_evidence.v1", "observedAt": time.time(),
            "checkpointPath": str(checkpoint.relative_to(root)), "claimVerification": "not_independently_verified"}
    try:
        checkpoint.resolve(strict=True).relative_to(root)
        if checkpoint.stat().st_size > 262144:
            raise ValueError("Checkpoint exceeds the read limit")
        value = json.loads(checkpoint.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "neyvia.operating_checkpoint.v1":
            raise ValueError("Unsupported checkpoint schema")
        files = value.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 100:
            raise ValueError("Checkpoint requires between 1 and 100 file references")
        checks = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("Malformed file reference")
            raw = item["path"]
            expected = item.get("sha256", "")
            actual = None
            reason = "missing_or_outside_workspace"
            try:
                path = (root / raw).resolve(strict=True)
                path.relative_to(root)
                if not path.is_file() or path.stat().st_size > 16777216:
                    reason = "not_a_file_or_exceeds_read_limit"
                else:
                    actual = sha256_file(path)
                    reason = "matches" if actual == expected else "changed"
            except (OSError, ValueError):
                pass
            checks.append({"path": raw, "status": reason, "matches": actual is not None and actual == expected})
        gates = value.get("gates", [])
        if not isinstance(gates, list) or len(gates) > 40 or any(not isinstance(g, dict) for g in gates):
            raise ValueError("Malformed completion gates")
        return {**base, "status": "current" if all(c["matches"] for c in checks) else "stale",
                "recordedAt": value.get("recordedAt"), "files": checks,
                "gates": [{"name": str(g.get("name", ""))[:200], "reportedStatus": str(g.get("status", "unknown"))[:80],
                           "evidence": str(g.get("evidence", ""))[:2000]} for g in gates]}
    except FileNotFoundError:
        return {**base, "status": "missing", "files": [], "gates": []}
    except (OSError, ValueError, TypeError):
        return {**base, "status": "unreadable", "files": [], "gates": []}
