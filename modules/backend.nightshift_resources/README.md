# nightshift_resources

Admission and event-driven limits; cancellation retains the repository lock.

- **Public API:** `Resources`, `positive`, `quiet_window`, `validate_policy`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.plan-hold`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.neyvia_missions](../backend.neyvia_missions/README.md), [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/nightshift_resources.py](../../src/grant_agent/nightshift_resources.py).
