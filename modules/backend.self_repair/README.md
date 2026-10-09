# self_repair

Provides backend / self_repair in Neyvia.

- **Public API:** `SelfRepairContractError`, `execute_self_repair_job`, `is_self_repair_job`, `queue_self_repair_job`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e-wz.repair-blocked`, `proofs-e-wz.repair-bounds`, `proofs-e-wz.repair-receipt`.
- **Dependencies:** [backend.proofs_e_wz](../backend.proofs_e_wz/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/self_repair.py](../../src/grant_agent/self_repair.py).
