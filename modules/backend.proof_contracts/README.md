# proof_contracts

Host-side manual contracts. Trusted local code, never eval or manual imports.

- **Public API:** `ContractViolation`, `after_action`, `before_action`, `catalog`, `declarations`, `file_digest`, `invoke`, `manifest_files`, `source_binding_digest`, `source_bindings`, `source_digest`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d-ui.view-arrange`, `d-ui.view-controls`, `d-ui.view-schemas`, `outputs.backend-publication-byte-recovery`, `proofs.manual-input`, `proofs.manual-output`.
- **Dependencies:** [backend.cl.manual_routing](../backend.cl.manual_routing/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_contracts.py](../../src/grant_agent/proof_contracts.py).
