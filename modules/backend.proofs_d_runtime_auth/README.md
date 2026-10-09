# proofs_d_runtime_auth

Transaction-local provider circuit and secret-free auth-queue contracts.

- **Public API:** `check_circuit_reporting`, `check_circuit_reset`, `check_circuit_result`, `check_classification`, `check_queue_payload`, `check_queue_present`, `check_queue_save`, `check_queue_transition`, `check_worker_circuit_before_completion`, `check_worker_doctor`, `circuit_admission`, `classification`, `observed_worker_capabilities`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.auth-queue.flow`, `d.runtime.auth-queue.persisted`, `d.runtime.auth-queue.projection`, `d.runtime.auth-queue.startup`, `d.runtime.auth-queue.state`, `d.runtime.auth-queue.transition`, `d.runtime.circuit.admission`, `d.runtime.circuit.classification`, `d.runtime.circuit.reporting`, `d.runtime.circuit.reset`, `d.runtime.circuit.transition`, `d.runtime.circuit.worker`.
- **Dependencies:** [backend.cluster](../backend.cluster/README.md), [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md), [backend.provider_auth_queue](../backend.provider_auth_queue/README.md), [backend.worker](../backend.worker/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_d_runtime_auth.py](../../src/grant_agent/proofs_d_runtime_auth.py).
