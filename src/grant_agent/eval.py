from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import json
from pathlib import Path


@_proofs_b_checked("proofs-b.engine.summary")
def summarize_runs(base_dir: Path) -> dict:
    sessions = [p for p in base_dir.glob("session_*") if p.is_dir()]
    if not sessions:
        return {
            "total_sessions": 0,
            "sessions_with_handoff": 0,
            "verification_failures": 0,
            "verification_commands": 0,
            "blocked_commands": 0,
            "runs_with_doc_evidence": 0,
            "runs_with_memory_writes": 0,
            "runs_with_checkpoints": 0,
            "average_context_usage_ratio": 0.0,
        }

    sessions_with_handoff = 0
    verification_failures = 0
    verification_commands = 0
    blocked_commands = 0
    runs_with_doc_evidence = 0
    runs_with_memory_writes = 0
    runs_with_checkpoints = 0
    usage_ratios: list[float] = []

    for session in sessions:
        if list(session.glob("handoff_packet_*.json")):
            sessions_with_handoff += 1

        state_path = session / "state.json"
        if not state_path.exists():
            continue
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if payload.get("doc_evidence"):
            runs_with_doc_evidence += 1
        if payload.get("memory_item_ids"):
            runs_with_memory_writes += 1
        if (session / "checkpoints").exists() and list((session / "checkpoints").glob("ckpt_*.json")):
            runs_with_checkpoints += 1
        context = payload.get("context", {})
        usage_ratio = context.get("usage_ratio")
        if isinstance(usage_ratio, (int, float)):
            usage_ratios.append(float(usage_ratio))

        for result in payload.get("verification_results", []):
            verification_commands += 1
            if result.get("status") == "blocked":
                blocked_commands += 1
            if result.get("return_code", 1) != 0:
                verification_failures += 1

    average_usage = sum(usage_ratios) / len(usage_ratios) if usage_ratios else 0.0
    return {
        "total_sessions": len(sessions),
        "sessions_with_handoff": sessions_with_handoff,
        "verification_failures": verification_failures,
        "verification_commands": verification_commands,
        "blocked_commands": blocked_commands,
        "runs_with_doc_evidence": runs_with_doc_evidence,
        "runs_with_memory_writes": runs_with_memory_writes,
        "runs_with_checkpoints": runs_with_checkpoints,
        "average_context_usage_ratio": round(average_usage, 3),
    }
