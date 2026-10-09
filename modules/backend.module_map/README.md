# module_map

Generate a navigable module map from source ownership, imports and CL manuals.

- **Public API:** `check`, `configuration_hashes`, `documentation`, `file_identity`, `generate`, `inventory`, `is_source_file`, `manual_documents`, `native_catalog`, `private_source`, `source_digest`, `source_hashes`, `source_texts`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.module-discovery`, `p22.module-registry`.
- **Dependencies:** [backend.contract_coverage](../backend.contract_coverage/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.module_plugins](../backend.module_plugins/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md), [backend.neyvia_modules](../backend.neyvia_modules/README.md), [backend.proof_credential_guard](../backend.proof_credential_guard/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/module_map.py](../../src/grant_agent/module_map.py).
