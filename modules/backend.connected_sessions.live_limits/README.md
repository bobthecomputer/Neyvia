# live_limits

Read quotas through the installed CLIs. No credential files or raw terminal receipts.

- **Public API:** `LimitsUnavailable`, `LiveLimits`, `existing_service`, `parse_claude_usage`, `read_claude`, `read_claude_preferring_mod`, `read_codex`, `read_opencode`, `service_for`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.chat-history-sidebar-journey`.
- **Dependencies:** [backend.connected_sessions.claude_terminal](../backend.connected_sessions.claude_terminal/README.md), [backend.connected_sessions.claude_trust](../backend.connected_sessions.claude_trust/README.md), [backend.connected_sessions.codex_rpc](../backend.connected_sessions.codex_rpc/README.md), [backend.connected_sessions.plan_limits](../backend.connected_sessions.plan_limits/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/live_limits.py](../../src/grant_agent/connected_sessions/live_limits.py).
