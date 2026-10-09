# native_device_operator_signing_wire

Opaque signing-wire package for paired-device operator approvals.

- **Public API:** `deny_operator_approval`, `inspect_signing_request`, `prepare_signing_request`, `submit_operator_signature`, `validate_signing_request_against_store`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.operator.retry`, `native.operator.wire`.
- **Dependencies:** [backend.native_device_operator_authority](../backend.native_device_operator_authority/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_device_operator_signing_wire.py](../../src/grant_agent/native_device_operator_signing_wire.py).
