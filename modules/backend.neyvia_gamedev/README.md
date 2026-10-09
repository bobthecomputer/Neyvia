# neyvia_gamedev

Project-scoped live editor bridges and durable, affinity-bound receipts.

- **Public API:** `GameDev`, `call`, `forward_command`, `handle_command`, `installed_editor`, `report_state`, `serve_http`, `service_for`, `sessions_snapshot`, `stamp`, `trusted_origin`, `validate_asset`, `neyvia.gamedev.action`, `neyvia.gamedev.asset_validate`, `neyvia.gamedev.project_status`, `neyvia.gamedev.receipt`, `neyvia.gamedev.receipts`, `neyvia.gamedev.sessions`, `neyvia.gamedev.setup`, `neyvia.gamedev.state`, `neyvia.gamedev.status`.
- **Manual:** [game-dev.cl](../../manuals/cl/game-dev.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `gamedev.export-validation-journey`, `p22.gamedev.screen-state-persistence`.
- **Dependencies:** [backend.connected_sessions.forward](../backend.connected_sessions.forward/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / game-dev.
- **Files:** [src/grant_agent/neyvia_gamedev.py](../../src/grant_agent/neyvia_gamedev.py).
