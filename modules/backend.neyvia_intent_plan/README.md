# neyvia_intent_plan

Model-authored intent plans; validation and publication make no provider call.

- **Public API:** `claude_turn_args`, `codex_thread_params`, `intent_instructions`, `native_plan_tool`, `needs_checklist`, `publish_plan`, `turn_note`, `validate_plan`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cl.goals](../backend.cl.goals/README.md), [backend.cl.protocol](../backend.cl.protocol/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_awareness](../backend.neyvia_awareness/README.md), [backend.paul_manual](../backend.paul_manual/README.md), [backend.proofs_c_intent](../backend.proofs_c_intent/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_intent_plan.py](../../src/grant_agent/neyvia_intent_plan.py).
