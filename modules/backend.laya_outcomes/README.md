# laya_outcomes

Durable app outcome queue: posting is outside the user action's critical path.

- **Public API:** `enqueue`, `flush`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.laya_client.contracts](../backend.laya_client.contracts/README.md), [backend.laya_hooks](../backend.laya_hooks/README.md), [backend.laya_service](../backend.laya_service/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/laya_outcomes.py](../../src/grant_agent/laya_outcomes.py).
