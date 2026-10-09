# claude_plan_history

Selective historical checklist scan; ordinary transcript text is never JSON-decoded here.

- **Public API:** `apply_plan_result`, `read_plan_history`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sessions.plan-history.conversation-scope`, `sessions.plan-history.order`, `sessions.plan-history.source-clear`.
- **Dependencies:** [backend.connected_sessions.claude_items](../backend.connected_sessions.claude_items/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/claude_plan_history.py](../../src/grant_agent/connected_sessions/claude_plan_history.py).
