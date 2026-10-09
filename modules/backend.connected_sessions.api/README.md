# api

HTTP and command surface of the connected-sessions broker.

- **Public API:** `handle_connected_command`, `respond_connected_command`, `serve_connected_get`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sessions.api.allowlist`, `sessions.api.authority`, `sessions.api.media`, `sessions.api.poll`, `sessions.api.response`, `sessions.api.sse`, `sessions.api.state_root`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_chat_media](../backend.connected_chat_media/README.md), [backend.connected_sessions.__init__](../backend.connected_sessions.__init__/README.md), [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connected_sessions.dashboard](../backend.connected_sessions.dashboard/README.md), [backend.connected_sessions.folder_jobs](../backend.connected_sessions.folder_jobs/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.connected_sessions.workspace](../backend.connected_sessions.workspace/README.md), [backend.cue_memory](../backend.cue_memory/README.md), [backend.neyvia_conductor](../backend.neyvia_conductor/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.prompt_amplifier](../backend.prompt_amplifier/README.md), [backend.task_feedback](../backend.task_feedback/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/api.py](../../src/grant_agent/connected_sessions/api.py).
