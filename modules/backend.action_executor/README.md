# action_executor

Provides backend / action_executor in Neyvia.

- **Public API:** `ExecutionAdapter`, `HybridExecutionAdapter`, `build_action_proposal`, `build_execution_policy`, `cleanup_execution_scope`, `delegated_cycle_phase_for_step`, `execute_action`, `normalize_execution_policy`, `prepare_execution_scope`, `requested_scope_for_execution_target`, `neyvia.verify`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.execution-cleanup`, `control.execution-phase`, `control.execution-proposal`, `control.execution-result`, `control.execution-scope`, `native.tools.routing`, `sv.video.route`.
- **Dependencies:** [backend.crashproof](../backend.crashproof/README.md), [backend.execution_truth](../backend.execution_truth/README.md), [backend.models](../backend.models/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_d_native](../backend.proofs_d_native/README.md), [backend.proofs_e_sv](../backend.proofs_e_sv/README.md), [backend.research](../backend.research/README.md), [backend.runtime_supervisor](../backend.runtime_supervisor/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.safety](../backend.safety/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia-core.
- **Files:** [src/grant_agent/action_executor.py](../../src/grant_agent/action_executor.py).
