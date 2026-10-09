# proofs_e_host

Production invariants for owned OS probes and portable host observations.

- **Public API:** `check_action_completion`, `check_import_closure`, `check_limits`, `check_safe_receipt`, `check_startup_readiness`, `check_writer_home`, `require`, `self_check`, `writer_result`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs.background-readiness`.
- **Dependencies:** [backend.action_receipts](../backend.action_receipts/README.md), [backend.cl.manuals](../backend.cl.manuals/README.md), [backend.cl.schema](../backend.cl.schema/README.md), [backend.connected_sessions.plan_limits](../backend.connected_sessions.plan_limits/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md), [backend.proof_credential_guard](../backend.proof_credential_guard/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_e_host.py](../../src/grant_agent/proofs_e_host.py).
