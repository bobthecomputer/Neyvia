# continuity_policy

Durable, risk-aware mission continuity for Neyvia.

- **Public API:** `MissionContinuityStore`, `classify_action`, `classify_gpu_control_action`, `proportional_verification`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.continuity.attempt`, `a-cli.continuity.gpu`, `a-cli.continuity.gpu-label`, `a-cli.continuity.recovery`, `a-cli.continuity.verification`, `proofs-c.missions.continuity-durable`, `proofs-c.missions.gpu-policy`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.proofs_c_missions](../backend.proofs_c_missions/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/continuity_policy.py](../../src/grant_agent/continuity_policy.py).
