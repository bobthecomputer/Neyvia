# folder_sync

Permissioned Syncthing control with scoped checksums and safe activation.

- **Public API:** `FolderSyncService`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `adapters.sync.compatibility`, `adapters.sync.discovery`, `adapters.sync.plan-activation`, `adapters.sync.policy`, `adapters.sync.recovery`, `adapters.sync.rollback`, `adapters.sync.stale`.
- **Dependencies:** [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.durability](../backend.durability/README.md), [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/folder_sync.py](../../src/grant_agent/folder_sync.py).
