# plan

An agent's own checklist, as data: Claude Code's TodoWrite and task tools, Codex's plan, Neyvia runs.

- **Public API:** `apply_op`, `latest_plan`, `note_task_created`, `plan_op`, `plan_summary`, `replace_steps`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.plan-transitions`, `sessions.plan-history.order`, `sessions.plan-history.source-clear`.
- **Dependencies:** [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/plan.py](../../src/grant_agent/connected_sessions/plan.py).
