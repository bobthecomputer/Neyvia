# neyviaChatRecovery

Provides INTERRUPTED_CHAT_SOURCE, UNREGISTERED_TURN_GRACE_MS, MISSING_RESULT_GRACE_MS, QUIET_RESPONSE_MS for Neyvia's UI state and behavior.

- **Public API:** `INTERRUPTED_CHAT_SOURCE`, `MISSING_RESULT_GRACE_MS`, `QUIET_RESPONSE_MS`, `UNREGISTERED_TURN_GRACE_MS`, `chatRecoveryDecision`, `interruptedChatTurnPatch`, `interruptedToolCalls`, `mergeStreamedTrace`, `quietResponseLabel`, `recordedResultChatTurnPatch`, `unownedPendingChatTurns`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `recovery.decision`, `recovery.interrupted`, `recovery.merge`, `recovery.quiet`, `recovery.recorded`, `recovery.unowned`.
- **Dependencies:** [surface.chatCancellation](../surface.chatCancellation/README.md), [surface.neyviaChatStream](../surface.neyviaChatStream/README.md), [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / neyviaChatRecovery.
- **Files:** [web/src/neyvia/neyviaChatRecovery.js](../../web/src/neyvia/neyviaChatRecovery.js).
