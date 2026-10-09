# claude_code_mods

Neyvia's tools as a Claude Code plugin (``plugins/neyvia``): the setting, the launch environment, the mod's reports.

- **Public API:** `call`, `launch_env`, `mod_active`, `plugin_ready`, `record_report`, `run_env`, `settings`, `neyvia.activity`, `neyvia.claude.mods`, `neyvia.claude.open_cli`, `neyvia.claude.runs`, `neyvia.message`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [runtime-provider.cl](../../manuals/cl/runtime-provider.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.mods.launch`, `a-cli.mods.report`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.claude_terminal](../backend.connected_sessions.claude_terminal/README.md), [backend.connected_sessions.live_limits](../backend.connected_sessions.live_limits/README.md), [backend.connected_sessions.plan_limits](../backend.connected_sessions.plan_limits/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / agents.
- **Files:** [src/grant_agent/claude_code_mods.py](../../src/grant_agent/claude_code_mods.py).
