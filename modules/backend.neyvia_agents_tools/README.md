# neyvia_agents_tools

neyvia.agents.state: the bot side of the agents dashboard, on the same read the UI shows.

- **Public API:** `call`, `neyvia.agents.deliveries`, `neyvia.agents.limits`, `neyvia.agents.overview`, `neyvia.agents.state`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.agents_message](../backend.agents_message/README.md), [backend.agents_overview](../backend.agents_overview/README.md), [backend.connected_sessions.dashboard](../backend.connected_sessions.dashboard/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md).
- **Owner:** Neyvia / agents.
- **Files:** [src/grant_agent/neyvia_agents_tools.py](../../src/grant_agent/neyvia_agents_tools.py).
