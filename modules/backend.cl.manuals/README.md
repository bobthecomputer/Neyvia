# manuals

Authored CL manuals compile to the existing safe, typed manual runner.

- **Public API:** `cl_to_manual`, `manual_to_cl`, `render_chapter`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.compiled-command`, `p22.manual-cache`, `p22.manual-compiler`.
- **Dependencies:** [backend.cl.parser](../backend.cl.parser/README.md), [backend.cl.schema](../backend.cl.schema/README.md), [backend.manual_contracts](../backend.manual_contracts/README.md), [backend.native_tools](../backend.native_tools/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/cl/manuals.py](../../src/grant_agent/cl/manuals.py).
