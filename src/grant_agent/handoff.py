from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from .context_manager import ContextWindowManager
from .models import HandoffPacket, PromptStack, RunState, VerificationResult, utc_now_iso
from .proofs_b_adapters import checked as _proofs_b_checked
from .durability import atomic_write_text


def _verification_dicts(results: list[VerificationResult]) -> list[dict]:
    return [asdict(item) for item in results]


@_proofs_b_checked("handoff")
def create_handoff_packet(
    session_id: str,
    parent_session_id: str | None,
    reason: str,
    state: RunState,
    prompt_stack: PromptStack,
    context_manager: ContextWindowManager,
) -> HandoffPacket:
    progress = {
        "completed_steps": state.completed_steps,
        "remaining_steps": [step for step in state.plan_steps if step not in state.completed_steps],
        "usage_ratio": round(context_manager.usage_ratio, 3),
        "context_status": context_manager.status(),
    }
    resume = [
        "Start new session with this handoff packet as mandatory context.",
        "Continue from remaining plan steps before adding new scope.",
        "Re-run acceptance checks after next implementation batch.",
    ]
    return HandoffPacket(
        schema_version="1.0.0",
        generated_at=utc_now_iso(),
        reason=reason,
        session_id=session_id,
        parent_session_id=parent_session_id,
        objective=state.objective,
        prompt_stack=asdict(prompt_stack),
        progress=progress,
        changed_files=state.changed_files,
        decisions=state.decisions,
        risks=state.risks,
        acceptance_checks=state.acceptance_checks,
        verification=_verification_dicts(state.verification_results),
        next_actions=state.next_actions,
        resume_instructions=resume,
    )


def save_handoff_packet(packet: HandoffPacket, session_path: Path, sequence: int) -> Path:
    output_path = session_path / f"handoff_packet_{sequence:03d}.json"
    from .harness_jobs import _exclusive_job_lock
    with _exclusive_job_lock(output_path, timeout_seconds=20):
        atomic_write_text(output_path, json.dumps(asdict(packet), indent=2).replace("\n", os.linesep))
    return output_path
