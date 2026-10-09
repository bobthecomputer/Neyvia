# proofs_d_nearby

Nearby transfer action contracts and bounded real loopback protocol lab.

- **Public API:** `check_ack_progress`, `check_cancel_request`, `check_cancel_transport`, `check_chunk_receipt`, `check_plan`, `check_resume_authorization`, `check_transfer_result`, `check_verified_file`, `require`, `self_check`.
- **Manual:** [nearby-send-runtime.cl](../../manuals/cl/nearby-send-runtime.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.nearby.cancel-truth`, `d.nearby.chunk-ack-integrity`, `d.nearby.durable-ack-prefix`, `d.nearby.hash-bound-plan`, `d.nearby.legacy-migration`, `d.nearby.resume-integrity`, `d.nearby.terminal-receipt`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.nearby_send](../backend.nearby_send/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / nearby-send-runtime.
- **Files:** [src/grant_agent/proofs_d_nearby.py](../../src/grant_agent/proofs_d_nearby.py).
