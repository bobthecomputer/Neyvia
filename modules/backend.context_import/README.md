# context_import

Selective, provider-neutral context import with durable lineage.

- **Public API:** `import_selection`, `list_imports`, `preview_export`, `read_import_selection`, `source_catalog`, `stage_upload`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.import-preview`, `control.import-read`, `control.import-selection`, `control.import-upload`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/context_import.py](../../src/grant_agent/context_import.py).
