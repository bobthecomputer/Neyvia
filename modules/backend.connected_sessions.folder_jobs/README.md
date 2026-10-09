# folder_jobs

Durable, hidden worktree checkout jobs independent of the request/service lifetime.

- **Public API:** `checkout_progress`, `run_job`, `start`, `status`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.chat-history-sidebar-journey`.
- **Dependencies:** [backend.chat_run_control](../backend.chat_run_control/README.md), [backend.durability](../backend.durability/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/folder_jobs.py](../../src/grant_agent/connected_sessions/folder_jobs.py).
