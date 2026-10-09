# native_checkpoints

Content-addressed, workspace-bounded checkpoints for Neyvia Native.

- **Public API:** `NativeCheckpointStore`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.checkpoints.authority`, `native.checkpoints.capture`, `native.checkpoints.preflight`, `native.checkpoints.recovery`, `native.checkpoints.restore`, `native.checkpoints.rollback`, `native.checkpoints.scope`.
- **Dependencies:** [backend.proofs_d_native](../backend.proofs_d_native/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_checkpoints.py](../../src/grant_agent/native_checkpoints.py).
