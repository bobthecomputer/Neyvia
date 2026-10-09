# cl_conformance

Run production CL syntax/semantic audits without executing tool effects.

- **Public API:** `main`, `neyvia.notes.write`.
- **Manual:** [handoff-recovery.cl](../../manuals/cl/handoff-recovery.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [notes.cl](../../manuals/cl/notes.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cl.manuals](../backend.cl.manuals/README.md), [backend.cl.schema](../backend.cl.schema/README.md), [backend.cl.validator](../backend.cl.validator/README.md), [backend.native_tools](../backend.native_tools/README.md).
- **Owner:** Neyvia / handoff-recovery.
- **Files:** [scripts/cl_conformance.py](../../scripts/cl_conformance.py).
