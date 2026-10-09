# agents_overview

One cached, read-only agent graph for the pane, CL and native clients.

- **Public API:** `Overview`, `aggregate`, `check_graph`, `new_tokens`, `node`, `overview`, `stamp`, `state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `agents.live-overview`.
- **Dependencies:** [backend.agents_overview_sources](../backend.agents_overview_sources/README.md), [backend.claude_code_host](../backend.claude_code_host/README.md), [backend.connected_sessions.dashboard](../backend.connected_sessions.dashboard/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.connected_sessions.runs](../backend.connected_sessions.runs/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.usage_report](../backend.usage_report/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/agents_overview.py](../../src/grant_agent/agents_overview.py).
