# claude_terminal

One Claude Code turn in its normal interactive mode, in a hidden terminal (the "plan limits" route).

- **Public API:** `ClaudeTerminalRun`, `attach_images_as_files`, `hook_python`, `screen_text`, `spawn_terminal`, `terminal_argv`, `terminal_available`.
- **Manual:** [host-runtime.cl](../../manuals/cl/host-runtime.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.host.policy-startup`, `providers.claude.events`, `providers.terminal.answer`, `providers.terminal.argv`, `providers.terminal.compact`, `providers.terminal.images`, `providers.terminal.screen`.
- **Dependencies:** [backend.claude_code_cli](../backend.claude_code_cli/README.md), [backend.claude_code_mods](../backend.claude_code_mods/README.md), [backend.connected_sessions.claude_items](../backend.connected_sessions.claude_items/README.md), [backend.connected_sessions.claude_stream](../backend.connected_sessions.claude_stream/README.md), [backend.connected_sessions.claude_transcript](../backend.connected_sessions.claude_transcript/README.md), [backend.connected_sessions.claude_trust](../backend.connected_sessions.claude_trust/README.md), [backend.connected_sessions.claude_usage](../backend.connected_sessions.claude_usage/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.transparency](../backend.connected_sessions.transparency/README.md), [backend.cua_launch](../backend.cua_launch/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.private_conpty](../backend.private_conpty/README.md), [backend.proofs_a_providers](../backend.proofs_a_providers/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / host-runtime.
- **Files:** [src/grant_agent/connected_sessions/claude_terminal.py](../../src/grant_agent/connected_sessions/claude_terminal.py).
