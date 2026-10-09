# nightshift

SQLite task board. Completion events, rather than a polling script, release work.

- **Public API:** `NightShift`, `folder_lock_key`, `nightshift_for`, `refresh_settings`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.neyvia_missions](../backend.neyvia_missions/README.md), [backend.neyvia_runtime](../backend.neyvia_runtime/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.nightshift_evidence](../backend.nightshift_evidence/README.md), [backend.nightshift_import](../backend.nightshift_import/README.md), [backend.nightshift_ledger](../backend.nightshift_ledger/README.md), [backend.nightshift_resources](../backend.nightshift_resources/README.md), [backend.nightshift_summary](../backend.nightshift_summary/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/nightshift.py](../../src/grant_agent/nightshift.py).
