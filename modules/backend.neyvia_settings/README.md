# neyvia_settings

Canonical owner preferences on the existing durable UI bus.

- **Public API:** `SettingsConflict`, `background_dir`, `call`, `effective_initiative`, `get`, `handle_command`, `network_check`, `read_background`, `save_background`, `setup`, `update`, `validate`, `validate_look`, `neyvia.settings.get`, `neyvia.settings.network_check`, `neyvia.settings.propose`, `neyvia.settings.setup`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [settings.cl](../../manuals/cl/settings.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d-ui.view-controls`, `p22.settings.preference-journey`, `settings.canonical-mirrors`, `settings.invalid-preserves`, `settings.legacy-theme`, `settings.night-policy-event`, `settings.revision-cas`.
- **Dependencies:** [backend.connected_sessions.claude_terminal](../backend.connected_sessions.claude_terminal/README.md), [backend.connected_sessions.sidebar_cleanup](../backend.connected_sessions.sidebar_cleanup/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.nightshift](../backend.nightshift/README.md), [backend.nightshift_resources](../backend.nightshift_resources/README.md), [backend.proofs_settings](../backend.proofs_settings/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_settings.py](../../src/grant_agent/neyvia_settings.py).
