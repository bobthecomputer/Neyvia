# proof_credential_guard

Proof workers refuse saved credentials outside their disposable state.

- **Public API:** `authorize_provider_transport`, `check_access`, `check_process`, `install`, `prepare_broker_fixture`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs.saved-credential-boundary`.
- **Dependencies:** [backend.proof_ports](../backend.proof_ports/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_credential_guard.py](../../src/grant_agent/proof_credential_guard.py).
