# claude_stream

One Claude Code turn: a persistent stream-json CLI process, its control protocol and the live events.

- **Public API:** `ClaudeRun`, `ClaudeSessionError`, `Pending`, `approval_data`, `build_argv`, `child_env`, `cli_prefix`, `declined_message`, `kill_process_tree`, `start_process`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `providers.claude.argv`, `providers.claude.environment`, `providers.claude.events`, `providers.claude.reply`, `providers.process.hidden`.
- **Dependencies:** [backend.claude_code_mods](../backend.claude_code_mods/README.md), [backend.connected_sessions.claude_items](../backend.connected_sessions.claude_items/README.md), [backend.connected_sessions.claude_transcript](../backend.connected_sessions.claude_transcript/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.plan_limits](../backend.connected_sessions.plan_limits/README.md), [backend.connected_sessions.transparency](../backend.connected_sessions.transparency/README.md), [backend.cua_launch](../backend.cua_launch/README.md), [backend.model_usage](../backend.model_usage/README.md), [backend.proofs_a_providers](../backend.proofs_a_providers/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/claude_stream.py](../../src/grant_agent/connected_sessions/claude_stream.py).
