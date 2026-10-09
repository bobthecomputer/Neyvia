# mission_watchdog

Provides backend / mission_watchdog in Neyvia.

- **Public API:** `build_mission_watchdog_report`, `build_planned_scope_artifacts`, `build_watchdog_problem_registry`, `build_watchdog_problem_report`, `build_watchdog_supervisor_state`, `enforce_fake_running_missions`, `ensure_watchdog_supervisor_loop`, `evaluate_fake_running_mission`, `load_watchdog_supervisor_state`, `parallel_dispatch_scope_evidence`, `prune_stale_generated_agent_runs`, `write_mission_watchdog_report`, `write_watchdog_supervisor_state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-b.engine.watchdog`, `proofs-b.engine.watchdog-enforce`.
- **Dependencies:** [backend.mission_receipts](../backend.mission_receipts/README.md), [backend.models](../backend.models/README.md), [backend.platform_config](../backend.platform_config/README.md), [backend.proofs_b_engine](../backend.proofs_b_engine/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/mission_watchdog.py](../../src/grant_agent/mission_watchdog.py).
