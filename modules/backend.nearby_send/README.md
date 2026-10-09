# nearby_send

LocalSend-compatible nearby transfer with pinned identity and receipts.

- **Public API:** `NearbySendService`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.nearby-history`, `d.host.nearby-recovery`, `d.host.nearby-redaction`, `d.nearby.cancel-truth`, `d.nearby.chunk-ack-integrity`, `d.nearby.durable-ack-prefix`, `d.nearby.hash-bound-plan`, `d.nearby.legacy-migration`, `d.nearby.resume-integrity`, `d.nearby.terminal-receipt`.
- **Dependencies:** [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.durability](../backend.durability/README.md), [backend.proofs_d_host](../backend.proofs_d_host/README.md), [backend.proofs_d_nearby](../backend.proofs_d_nearby/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/nearby_send.py](../../src/grant_agent/nearby_send.py).
