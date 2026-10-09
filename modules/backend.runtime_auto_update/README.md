# runtime_auto_update

Provides backend / runtime_auto_update in Neyvia.

- **Public API:** `blocked_tool_update`, `ensure_runtime_auto_update`, `keep_tools_updated`, `latest_runtime_auto_update_receipt`, `npm_package_dir`, `npm_package_of`, `record_tool_update`, `runtime_auto_update_receipt_path`, `runtime_in_use`, `tool_update_admission`, `update_user_global_clis`, `user_cli_update_receipt_path`, `user_npm_prefix`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sv.update.package-parse`.
- **Dependencies:** [backend.cli_installer](../backend.cli_installer/README.md), [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connections_install](../backend.connections_install/README.md), [backend.models](../backend.models/README.md), [backend.proofs_e_sv](../backend.proofs_e_sv/README.md), [backend.runtime_updates](../backend.runtime_updates/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/runtime_auto_update.py](../../src/grant_agent/runtime_auto_update.py).
