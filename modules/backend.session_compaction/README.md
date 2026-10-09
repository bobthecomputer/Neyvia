# session_compaction

Incremental, durable semantic compaction at the model-input boundary.

- **Public API:** `CompactionError`, `SessionCompactor`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `context.config.runtime-budget`.
- **Dependencies:** [backend.chat_context](../backend.chat_context/README.md), [backend.compaction_policy](../backend.compaction_policy/README.md), [backend.durability](../backend.durability/README.md), [backend.goal_loop](../backend.goal_loop/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/session_compaction.py](../../src/grant_agent/session_compaction.py).
