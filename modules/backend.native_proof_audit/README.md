# native_proof_audit

Deterministic final-workspace proof auditing for Neyvia Native.

- **Public API:** `NativeProofAuditor`, `WorkspaceSnapshot`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.audit.delta`, `native.audit.failure-gate`, `native.audit.proof-discovery`.
- **Dependencies:** [backend.proofs_d_native](../backend.proofs_d_native/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_proof_audit.py](../../src/grant_agent/native_proof_audit.py).
