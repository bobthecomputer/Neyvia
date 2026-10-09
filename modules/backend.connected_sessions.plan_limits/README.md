# plan_limits

Plan-limit windows (5-hour, weekly) as the apps themselves last reported them. Nothing is estimated.

- **Public API:** `all_limits`, `claude_limits`, `codex_limits`, `codex_windows`, `fresh_mod_rows`, `record_claude`, `record_claude_mod`, `record_claude_statusline`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.plan-limits`, `p22.plan-hold`, `proofs-e-host.limits`.
- **Dependencies:** [backend.connected_sessions.codex_items](../backend.connected_sessions.codex_items/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_e_host](../backend.proofs_e_host/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/connected_sessions/plan_limits.py](../../src/grant_agent/connected_sessions/plan_limits.py).
