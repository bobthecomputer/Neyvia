# updater_contract

Offline, fail-closed contract for signed Neyvia desktop updates.

- **Public API:** `UpdateProgress`, `UpdaterContract`, `UpdaterContractError`, `artifact_signature_payload`, `delta_signature_payload`, `hash_signed_manifest_payload`, `local_receipt_payload`, `manifest_signature_payload`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.dependency_inventory](../backend.dependency_inventory/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/updater_contract.py](../../src/grant_agent/updater_contract.py).
