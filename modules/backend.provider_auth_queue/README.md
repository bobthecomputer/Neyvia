# provider_auth_queue

Provides backend / provider_auth_queue in Neyvia.

- **Public API:** `ProviderAuthQueue`, `parse_provider_secret_store_payload`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.auth-queue.flow`, `d.runtime.auth-queue.persisted`, `d.runtime.auth-queue.projection`, `d.runtime.auth-queue.startup`, `d.runtime.auth-queue.state`, `d.runtime.auth-queue.transition`.
- **Dependencies:** [backend.proofs_d_runtime_auth](../backend.proofs_d_runtime_auth/README.md), [backend.provider_state_io](../backend.provider_state_io/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/provider_auth_queue.py](../../src/grant_agent/provider_auth_queue.py).
