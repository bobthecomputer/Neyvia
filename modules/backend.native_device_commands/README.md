# native_device_commands

Receipt-bound, human-authorized command queue for paired Neyvia devices.

- **Public API:** `NativeDeviceCommandStore`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.commands.approval`, `native.commands.cancel`, `native.commands.deadline`, `native.commands.final-gate`, `native.commands.idempotency`, `native.commands.receipt`, `native.commands.scope`, `native.commands.secret-free`, `native.commands.single-flight`, `native.commands.uncertainty`.
- **Dependencies:** [backend.native_pairing](../backend.native_pairing/README.md), [backend.proofs_d_native](../backend.proofs_d_native/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_device_commands.py](../../src/grant_agent/native_device_commands.py).
