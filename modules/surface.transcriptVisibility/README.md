# transcriptVisibility

Provides REAL_AGENT_DIALOGUE_SOURCES, REAL_RUNTIME_REPLY_SOURCES, TRANSCRIPT_ROLES, isRealAgentDialogueSource for Neyvia's UI state and behavior.

- **Public API:** `REAL_AGENT_DIALOGUE_SOURCES`, `REAL_RUNTIME_REPLY_SOURCES`, `TRANSCRIPT_ROLES`, `describeHiddenTurn`, `dialogueBody`, `isRealAgentDialogueSource`, `isRealRuntimeReplySource`, `transcriptTurnText`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `chat.runtime-source`, `chat.stopped-body`, `chat.stopped-visibility`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / transcriptVisibility.
- **Files:** [web/src/neyvia/transcriptVisibility.js](../../web/src/neyvia/transcriptVisibility.js).
