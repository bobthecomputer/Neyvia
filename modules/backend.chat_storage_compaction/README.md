# chat_storage_compaction

Shrink chat storage written before turns stored references instead of session windows.

- **Public API:** `compact_chat_storage`, `main`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.chat-storage-compaction-outcome`.
- **Dependencies:** [backend.chat_run_control](../backend.chat_run_control/README.md), [backend.neyvia_conversations](../backend.neyvia_conversations/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/chat_storage_compaction.py](../../src/grant_agent/chat_storage_compaction.py).
