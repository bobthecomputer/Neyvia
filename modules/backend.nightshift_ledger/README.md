# nightshift_ledger

Persisted night periods and every harness attempt, including failed retries.

- **Public API:** `attempt`, `begin`, `finish`, `initialize`, `period`, `record`, `recover_claude_usage`, `rename_run`, `summary`, `timestamp`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `nightshift.claude-session-usage`.
- **Dependencies:** [backend.connected_sessions.claude_usage](../backend.connected_sessions.claude_usage/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/nightshift_ledger.py](../../src/grant_agent/nightshift_ledger.py).
