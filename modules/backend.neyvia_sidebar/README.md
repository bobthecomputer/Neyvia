# neyvia_sidebar

Sidebar observation and durable preview/confirm/undo on the existing UI bus.

- **Public API:** `call`, `confirm`, `digest`, `forward_command`, `handle_command`, `observation`, `preview`, `respond_command`, `subject_name`, `undo`, `neyvia.sidebar.confirm`, `neyvia.sidebar.preview`, `neyvia.sidebar.state`, `neyvia.sidebar.undo`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [sidebar.cl](../../manuals/cl/sidebar.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.forward](../backend.connected_sessions.forward/README.md), [backend.connected_sessions.sidebar_cleanup](../backend.connected_sessions.sidebar_cleanup/README.md), [backend.neyvia_sidebar_projection](../backend.neyvia_sidebar_projection/README.md), [backend.neyvia_sidebar_semantics](../backend.neyvia_sidebar_semantics/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / agents.
- **Files:** [src/grant_agent/neyvia_sidebar.py](../../src/grant_agent/neyvia_sidebar.py).
