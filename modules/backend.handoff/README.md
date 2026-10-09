# handoff

Provides backend / handoff in Neyvia.

- **Public API:** `create_handoff_packet`, `save_handoff_packet`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `adapters.handoff.progress`.
- **Dependencies:** [backend.context_manager](../backend.context_manager/README.md), [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.models](../backend.models/README.md), [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/handoff.py](../../src/grant_agent/handoff.py).
