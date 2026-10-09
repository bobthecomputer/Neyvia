# usage_report

Token and plan-usage analytics for the Usage pane (GET /api/ui/usage).

- **Public API:** `api_equivalent`, `assemble`, `base_model`, `check_report`, `claude_usage_entry`, `overview_usage`, `price_for`, `report`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `nightshift.claude-session-usage`, `usage.endpoint.shape`, `usage.plan.api-equivalent-only`.
- **Dependencies:** [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.connected_sessions.plan_limits](../backend.connected_sessions.plan_limits/README.md), [backend.external_chat_inventory](../backend.external_chat_inventory/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/usage_report.py](../../src/grant_agent/usage_report.py).
