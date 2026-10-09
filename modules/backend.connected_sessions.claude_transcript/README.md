# claude_transcript

Incremental, tail-first reader for Claude Code session transcripts (``~/.claude/projects``).

- **Public API:** `AgentAggregate`, `ItemStore`, `LineFollower`, `StoreCache`, `SubagentIndex`, `SummaryIndex`, `aligned_records`, `apply_agent_result`, `config_dir`, `find_session_file`, `iter_session_files`, `new_agent_hints`, `read_bytes`, `read_line_at`, `split_records`, `user_prose`, `user_prose_text_of_sidechain`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.plan-history`, `p22.sessions.claude-incremental-transcript`, `providers.claude.aggregate`, `providers.claude.read_bytes`, `providers.claude.sequence`, `providers.claude.store_page`, `providers.claude.title_priority`, `transparency.helper-reports`.
- **Dependencies:** [backend.connected_chat_media](../backend.connected_chat_media/README.md), [backend.connected_sessions.claude_items](../backend.connected_sessions.claude_items/README.md), [backend.connected_sessions.claude_plan_history](../backend.connected_sessions.claude_plan_history/README.md), [backend.connected_sessions.model](../backend.connected_sessions.model/README.md), [backend.connected_sessions.plan](../backend.connected_sessions.plan/README.md), [backend.connected_sessions.transparency](../backend.connected_sessions.transparency/README.md), [backend.external_chat_inventory](../backend.external_chat_inventory/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_a_providers](../backend.proofs_a_providers/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/claude_transcript.py](../../src/grant_agent/connected_sessions/claude_transcript.py).
