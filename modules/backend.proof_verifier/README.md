# proof_verifier

Run production manual observers/procedures in a new, confined scratch root.

- **Public API:** `coverage_report`, `manual_self_checks`, `run_verification`, `worker_failure_message`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs.scratch-isolation`, `proofs.source-revalidation`, `proofs.worker-failure-report`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_inception](../backend.neyvia_inception/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md), [backend.proof_coverage](../backend.proof_coverage/README.md), [backend.proof_credential_guard](../backend.proof_credential_guard/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_verifier.py](../../src/grant_agent/proof_verifier.py).
