from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .proofs_b_desktop import checked

DEBUGGER_BUNDLE_SCHEMA = "fluxio.debugger_bundle.v1"
DIAGNOSTIC_SUMMARY_SCHEMA = "fluxio.diagnostic_summary.v1"


@checked("desktop.debugger.bundle")
def write_debugger_bundle(
    *,
    root: str | Path,
    mission_id: str,
    registry_snapshot: dict[str, Any] | None = None,
    process_tree: list[dict[str, Any]] | None = None,
    queue_state: dict[str, Any] | None = None,
    evidence_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    bundle_id = f"debugger_bundle_{uuid.uuid4().hex[:12]}"
    bundle_dir = root_path / ".agent_control" / "mission_runs" / _safe_path_part(mission_id) / "debugger_bundles" / bundle_id
    files_dir = bundle_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, str]] = []
    missing: list[str] = []
    for path in evidence_paths or []:
        source = Path(path)
        if not source.is_absolute():
            source = root_path / source
        if not source.exists() or not source.is_file():
            missing.append(str(path))
            continue
        target = files_dir / _safe_path_part(source.name)
        shutil.copy2(source, target)
        copied.append({"source": str(source), "bundlePath": str(target)})
    manifest = {
        "schema": DEBUGGER_BUNDLE_SCHEMA,
        "bundleId": bundle_id,
        "missionId": str(mission_id),
        "generatedAt": utc_now_iso(),
        "bundleDir": str(bundle_dir),
        "registrySnapshot": _compact_mapping(registry_snapshot or {}),
        "processTree": [_compact_mapping(item) for item in (process_tree or [])[:40]],
        "queueState": _compact_mapping(queue_state or {}),
        "copiedFiles": copied,
        "missingFiles": missing,
        "nextAction": (
            "Inspect copied evidence files and manifest to diagnose the mission."
            if copied or registry_snapshot or process_tree or queue_state
            else "Provide registry, process, queue, receipt, or runtime evidence before using this bundle."
        ),
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifestPath"] = str(manifest_path)
    return manifest


@checked("desktop.debugger.summary")
def build_diagnostic_summary(
    *,
    mission_id: str,
    flight_snapshot: dict[str, Any] | None = None,
    debugger_bundle: dict[str, Any] | None = None,
    latest_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    receipts = [item for item in (latest_receipts or []) if isinstance(item, dict)]
    failing_receipt = next(
        (
            item
            for item in reversed(receipts)
            if str(item.get("status") or item.get("decision") or "").lower()
            in {"failed", "blocked", "repair_needed", "skipped"}
        ),
        {},
    )
    snapshot = flight_snapshot or {}
    bundle = debugger_bundle or {}
    verifier_result = snapshot.get("verifierResult") if isinstance(snapshot.get("verifierResult"), dict) else {}
    what_failed = (
        failing_receipt.get("summary")
        or failing_receipt.get("stderrSummary")
        or verifier_result.get("summary")
        or ""
    )
    where_failed = (
        failing_receipt.get("phase")
        or failing_receipt.get("schema")
        or snapshot.get("currentPhase")
        or "unknown"
    )
    likely_why = (
        failing_receipt.get("nextAction")
        or failing_receipt.get("next_action")
        or snapshot.get("stderrTail")
        or "No failing receipt supplied; inspect the debugger bundle evidence."
    )
    proof_paths = []
    for item in receipts:
        proof_paths.extend(item.get("proof_paths", []) if isinstance(item.get("proof_paths"), list) else [])
        proof_paths.extend(item.get("proofPaths", []) if isinstance(item.get("proofPaths"), list) else [])
    proof_paths.extend(
        item.get("bundlePath", "")
        for item in bundle.get("copiedFiles", []) if isinstance(item, dict)
    )
    next_action = (
        failing_receipt.get("nextAction")
        or failing_receipt.get("next_action")
        or snapshot.get("nextRecoveryAction")
        or bundle.get("nextAction")
        or "Collect a flight recorder snapshot and failing receipt before continuing."
    )
    return {
        "schema": DIAGNOSTIC_SUMMARY_SCHEMA,
        "missionId": _compact_text(mission_id, 120),
        "status": "actionable" if (failing_receipt or proof_paths or snapshot or bundle) else "insufficient_evidence",
        "whatFailed": _compact_text(what_failed or "No concrete failure was identified.", 400),
        "whereFailed": _compact_text(where_failed, 180),
        "likelyWhy": _compact_text(likely_why, 500),
        "proofPaths": [item for item in _bounded_strings(proof_paths, limit=40, text_limit=240) if item],
        "nextAction": _compact_text(next_action, 300),
    }


def _compact_mapping(payload: dict[str, Any], *, limit: int = 40, text_limit: int = 300) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if len(compact) >= limit:
            break
        compact_key = _compact_text(key, 100)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[compact_key] = _compact_text(value, text_limit) if isinstance(value, str) else value
        elif isinstance(value, list):
            compact[compact_key] = [_compact_text(item, text_limit) for item in value[:20]]
        else:
            compact[compact_key] = _compact_text(value, text_limit)
    return compact


def _bounded_strings(values: list[Any], *, limit: int, text_limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _compact_text(value, text_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def _safe_path_part(value: object) -> str:
    text = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value or "item"))
    return text[:120] or "item"


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
