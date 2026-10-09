# native_device_operator_authority

Verify-only operator authority for paired-device command approvals.

- **Public API:** `OperatorAuthorizedDeviceCommandStore`, `OperatorDecisionVerifier`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.operator.final-gate`, `native.operator.pinned-verifier`, `native.operator.retry`, `native.operator.signature`.
- **Dependencies:** [backend.native_device_commands](../backend.native_device_commands/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_device_operator_authority.py](../../src/grant_agent/native_device_operator_authority.py).
