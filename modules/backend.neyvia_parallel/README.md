# neyvia_parallel

Parallel branches, one durable run with connected sessions and ordered Git merges.

- **Public API:** `action`, `activity`, `call`, `checks`, `deliver`, `lane`, `listen`, `load`, `merge`, `now`, `observe`, `options`, `pane_state`, `route`, `run_lock`, `save`, `start`, `stop_sessions`, `store`, `track`, `neyvia.parallel.answer`, `neyvia.parallel.ask`, `neyvia.parallel.done`, `neyvia.parallel.finish`, `neyvia.parallel.start`, `neyvia.parallel.state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [parallel.cl](../../manuals/cl/parallel.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.clean-start`, `parallel.committed-done`, `parallel.failed-start-settle`, `parallel.finish-authority`, `parallel.ordered-conflict`, `parallel.pending-question-retry`, `parallel.question-answer`, `parallel.resolution`, `parallel.safe-settle`, `parallel.separate-worktrees`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.claude_code_activity](../backend.claude_code_activity/README.md), [backend.claude_code_host](../backend.claude_code_host/README.md), [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.neyvia_runtime](../backend.neyvia_runtime/README.md).
- **Owner:** Neyvia / parallel.
- **Files:** [src/grant_agent/neyvia_parallel.py](../../src/grant_agent/neyvia_parallel.py).
