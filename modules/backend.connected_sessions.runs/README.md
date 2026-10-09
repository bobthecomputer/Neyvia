# runs

Durable run records for connected sessions, in ``.agent_control/connected_chats.sqlite3``.

- **Public API:** `RunStore`, `iso`, `public_run`, `request_fingerprint`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sessions.run.request`.
- **Dependencies:** [backend.chat_run_control](../backend.chat_run_control/README.md), [backend.connected_sessions.registry](../backend.connected_sessions.registry/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/runs.py](../../src/grant_agent/connected_sessions/runs.py).
