# mission_receipts

Provides backend / mission_receipts in Neyvia.

- **Public API:** `ReceiptValidationError`, `append_mission_receipt`, `load_mission_receipts`, `mission_receipts_path`, `validate_mission_receipt`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-c.missions.default-isolation`, `proofs-c.missions.receipt-durable`, `proofs-c.missions.receipt-filter`, `proofs-c.missions.receipt-schema`.
- **Dependencies:** [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.models](../backend.models/README.md), [backend.proofs_c_missions](../backend.proofs_c_missions/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/mission_receipts.py](../../src/grant_agent/mission_receipts.py).
