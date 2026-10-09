# neyvia_panes

The new shell's file, artifact and terminal panes (``pane.show``).

- **Public API:** `Terminal`, `call_panes`, `call_tool`, `default_shell`, `diff_file`, `open_artifact`, `open_terminal`, `read_file`, `serve_artifact`, `stat_artifact`, `stream_terminal`, `terminal`, `write_file`, `neyvia.pane.observe`, `neyvia.pane.state`, `neyvia.terminal.list`, `neyvia.terminal.read`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [neyvia-reference.cl](../../manuals/cl/neyvia-reference.cl), [workspace.cl](../../manuals/cl/workspace.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `outputs.backend-publication-byte-recovery`, `p22.workspace.output-journey`.
- **Dependencies:** [backend.claude_code_activity](../backend.claude_code_activity/README.md), [backend.claude_code_cli](../backend.claude_code_cli/README.md), [backend.connected_sessions.api](../backend.connected_sessions.api/README.md), [backend.connected_sessions.claude_terminal](../backend.connected_sessions.claude_terminal/README.md), [backend.neyvia_browser](../backend.neyvia_browser/README.md), [backend.neyvia_files_tools](../backend.neyvia_files_tools/README.md), [backend.neyvia_outputs](../backend.neyvia_outputs/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.private_conpty](../backend.private_conpty/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_panes.py](../../src/grant_agent/neyvia_panes.py).
