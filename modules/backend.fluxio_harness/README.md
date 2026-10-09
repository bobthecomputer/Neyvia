# fluxio_harness

Provides backend / fluxio_harness in Neyvia.

- **Public API:** `FluxioHarness`, `LegacyHarnessAdapter`, `build_route_outcome_trends`, `canonical_route_model`, `guided_profile_defaults`, `infer_task_route_profile`, `normalize_route_overrides`, `normalize_route_role`, `recommended_model_routes`, `resolve_efficiency_autotune_policy`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.scheduler.queued`, `proofs-b.engine.autotune`, `proofs-b.engine.route-equivalence`, `proofs-b.engine.routes`, `proofs-c.missions.security-route`.
- **Dependencies:** [backend.action_executor](../backend.action_executor/README.md), [backend.checkpoints](../backend.checkpoints/README.md), [backend.context_manager](../backend.context_manager/README.md), [backend.doc_ingestion](../backend.doc_ingestion/README.md), [backend.engine](../backend.engine/README.md), [backend.handoff](../backend.handoff/README.md), [backend.mission_control](../backend.mission_control/README.md), [backend.models](../backend.models/README.md), [backend.planner](../backend.planner/README.md), [backend.profiles](../backend.profiles/README.md), [backend.prompts](../backend.prompts/README.md), [backend.proofs_a_cli_scheduler](../backend.proofs_a_cli_scheduler/README.md), [backend.proofs_b_engine](../backend.proofs_b_engine/README.md), [backend.proofs_c_missions](../backend.proofs_c_missions/README.md), [backend.reporting](../backend.reporting/README.md), [backend.runtime_supervisor](../backend.runtime_supervisor/README.md), [backend.safety](../backend.safety/README.md), [backend.session_store](../backend.session_store/README.md), [backend.skill_library](../backend.skill_library/README.md), [backend.verification](../backend.verification/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/fluxio_harness.py](../../src/grant_agent/fluxio_harness.py).
