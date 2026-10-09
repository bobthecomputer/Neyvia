# claude_usage

Incremental per-turn Claude token spend, using the Usage pane's transcript interpretation.

- **Public API:** `ClaudeTranscriptUsage`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `nightshift.claude-session-usage`.
- **Dependencies:** [backend.connected_sessions.claude_transcript](../backend.connected_sessions.claude_transcript/README.md), [backend.usage_report](../backend.usage_report/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/claude_usage.py](../../src/grant_agent/connected_sessions/claude_usage.py).
