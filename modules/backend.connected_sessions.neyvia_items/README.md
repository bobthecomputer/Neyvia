# neyvia_items

Neyvia chat turns and chat-stream events as connected-session items.

- **Public API:** `LiveTurn`, `activity_segments`, `compaction_rows`, `merge_calls`, `normalize_tool_call`, `ordinal_of`, `receipt_of`, `route_of`, `segments_from`, `seq_for`, `tool_category`, `tool_item`, `tool_title`, `turn_items`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.live`, `sessions.neyvia.items`, `sessions.neyvia.tools`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.neyvia_options](../backend.connected_sessions.neyvia_options/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/neyvia_items.py](../../src/grant_agent/connected_sessions/neyvia_items.py).
