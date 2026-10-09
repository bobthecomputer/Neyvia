# claude_code_host

Neyvia's side of the Claude Code mod: the endpoints under ``/api/ui/claude-code/mod/`` (plan 29 section A).

- **Public API:** `bootstrap`, `call_tool`, `forget_run`, `held`, `hold`, `inbox`, `mint`, `mod_loaded`, `mod_name`, `note_memory`, `note_turn`, `publish_adhoc_token`, `queue_message`, `remember_checklist`, `report`, `revoke`, `secret_path`, `serve_http`, `session_for_run`, `state`, `stop`, `token_file`, `verify`, `warm`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.mod-worker-done`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.cl.integration](../backend.cl.integration/README.md), [backend.cl.protocol](../backend.cl.protocol/README.md), [backend.claude_code_activity](../backend.claude_code_activity/README.md), [backend.claude_code_mods](../backend.claude_code_mods/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_attention](../backend.neyvia_attention/README.md), [backend.neyvia_awareness](../backend.neyvia_awareness/README.md), [backend.neyvia_cl](../backend.neyvia_cl/README.md), [backend.neyvia_intent_plan](../backend.neyvia_intent_plan/README.md), [backend.neyvia_ui_api](../backend.neyvia_ui_api/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/claude_code_host.py](../../src/grant_agent/claude_code_host.py).
