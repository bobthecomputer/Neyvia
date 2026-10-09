# native_pairing

Scoped one-time pairing for Neyvia computer, phone, and NAS surfaces.

- **Public API:** `NativePairingStore`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.commands.final-gate`, `native.commands.secret-free`, `native.pairing.authority`, `native.pairing.digest`, `native.pairing.scope-input`, `native.pairing.single-use`.
- **Dependencies:** [backend.proofs_d_native](../backend.proofs_d_native/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_pairing.py](../../src/grant_agent/native_pairing.py).
