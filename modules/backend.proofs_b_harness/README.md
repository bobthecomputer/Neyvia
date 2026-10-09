# proofs_b_harness

Executable contracts for durable local Harness actions.

- **Public API:** `check_admission`, `check_budget_input`, `check_catalog`, `check_execution_snapshot`, `check_gateway`, `check_instruction`, `check_liveness_outcome`, `check_observation`, `check_profile`, `check_write`, `registry_projection`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-b.harness.admission`, `proofs-b.harness.budget`, `proofs-b.harness.budget-input`, `proofs-b.harness.catalog`, `proofs-b.harness.execution`, `proofs-b.harness.gateway`, `proofs-b.harness.identity`, `proofs-b.harness.instruction`, `proofs-b.harness.lifecycle`, `proofs-b.harness.lock-recovery`, `proofs-b.harness.model-policy`, `proofs-b.harness.observation`, `proofs-b.harness.policy`, `proofs-b.harness.public-profile`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.harness_execution_capacity](../backend.harness_execution_capacity/README.md), [backend.harness_job_worker](../backend.harness_job_worker/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.harness_registry](../backend.harness_registry/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.runtimes.managed_cli](../backend.runtimes.managed_cli/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_b_harness.py](../../src/grant_agent/proofs_b_harness.py).
