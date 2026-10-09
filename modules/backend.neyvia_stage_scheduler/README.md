# neyvia_stage_scheduler

Execute compiled NEYVIA/1 stages with best-checkpoint rollback receipts.

- **Public API:** `NeyviaStageScheduler`, `StepOutcome`, `build_progressive_step_handler`, `default_step_handler`, `execute_neyvia_stages`, `normalize_compiled_plan`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.stage-parallel`, `d.host.stage-receipt`, `d.host.stage-refusal`, `d.host.stage-tool-authority`.
- **Dependencies:** [backend.capability_service](../backend.capability_service/README.md), [backend.mcp_broker](../backend.mcp_broker/README.md), [backend.orchestration_language](../backend.orchestration_language/README.md), [backend.progressive_tools](../backend.progressive_tools/README.md), [backend.proofs_d_host](../backend.proofs_d_host/README.md), [backend.semantic_dispatch](../backend.semantic_dispatch/README.md), [backend.ui_tools](../backend.ui_tools/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_stage_scheduler.py](../../src/grant_agent/neyvia_stage_scheduler.py).
