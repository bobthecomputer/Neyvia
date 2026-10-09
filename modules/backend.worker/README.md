# worker

Provides backend / worker in Neyvia.

- **Public API:** `build_worker_doctor`, `execute_job`, `main`, `run_controller_worker_once`, `run_local_worker_once`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.scheduler.environment`, `a-cli.scheduler.execute`, `a-cli.scheduler.lifecycle`, `a-cli.scheduler.threads`, `a-cli.scheduler.unlimited-loop`, `a-cli.scheduler.worker`, `d.runtime.circuit.worker`, `proofs-e-wz.worker-repair`.
- **Dependencies:** [backend.cluster](../backend.cluster/README.md), [backend.computer_use_twin](../backend.computer_use_twin/README.md), [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.proofs_a_cli_scheduler](../backend.proofs_a_cli_scheduler/README.md), [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md), [backend.proofs_d_runtime_auth](../backend.proofs_d_runtime_auth/README.md), [backend.proofs_e_wz](../backend.proofs_e_wz/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.self_repair](../backend.self_repair/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/worker.py](../../src/grant_agent/worker.py).
