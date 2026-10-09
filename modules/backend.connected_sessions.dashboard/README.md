# dashboard

Everything working right now, in one read: the agents dashboard (UI) and ``neyvia.agents.state`` (bot).

- **Public API:** `build`, `doing_now`, `running_inventory`, `subagents`, `work_board`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.plan-dashboard`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.claude_code_mods](../backend.claude_code_mods/README.md), [backend.connected_sessions.claude_items](../backend.connected_sessions.claude_items/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.neyvia_cua](../backend.neyvia_cua/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/dashboard.py](../../src/grant_agent/connected_sessions/dashboard.py).
