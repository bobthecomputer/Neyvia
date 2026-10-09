# neyvia_awareness

Awareness: a shared work board (who works on which files), the impact map and the intent checklist.

- **Public API:** `board_list`, `board_path`, `call`, `claim`, `handle_command`, `intent_checklist`, `overlaps`, `release`, `release_owner`, `neyvia.impact`, `neyvia.intent.checklist`, `neyvia.plan.update`, `neyvia.work.claim`, `neyvia.work.list`, `neyvia.work.release`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [awareness.cl](../../manuals/cl/awareness.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `awareness.claim.overlaps`, `awareness.claim.persisted`, `awareness.claim.refresh`, `awareness.claim.staleness`, `awareness.list.projection`, `awareness.paths.overlap`, `awareness.release.persisted`.
- **Dependencies:** [backend.chat_run_control](../backend.chat_run_control/README.md), [backend.neyvia_impact](../backend.neyvia_impact/README.md), [backend.neyvia_intent_plan](../backend.neyvia_intent_plan/README.md), [backend.paul_manual](../backend.paul_manual/README.md), [backend.proofs_awareness](../backend.proofs_awareness/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / agents.
- **Files:** [src/grant_agent/neyvia_awareness.py](../../src/grant_agent/neyvia_awareness.py).
