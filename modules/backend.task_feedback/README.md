# task_feedback

Terminal task feedback, shared by connected UI and workspace tools.

- **Public API:** `FeedbackStore`, `call`, `capture_outputs`, `handle_command`, `public_feedback`, `neyvia.feedback.get`, `neyvia.feedback.submit`, `neyvia.lessons.list`, `neyvia.lessons.revert`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connected_sessions.registry](../backend.connected_sessions.registry/README.md), [backend.connected_sessions.runs](../backend.connected_sessions.runs/README.md), [backend.lesson_evolver](../backend.lesson_evolver/README.md), [backend.neyvia_ui_client](../backend.neyvia_ui_client/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia-core.
- **Files:** [src/grant_agent/task_feedback.py](../../src/grant_agent/task_feedback.py).
