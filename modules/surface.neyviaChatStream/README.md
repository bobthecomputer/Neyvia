# neyviaChatStream

Provides normalizeNeyviaChatActivitySegments, applyNeyviaChatStreamEvents, startNeyviaChatStreamPoll, createNeyviaChatStreamState for Neyvia's UI state and behavior.

- **Public API:** `applyNeyviaChatStreamEvents`, `createNeyviaChatStreamState`, `neyviaChatTraceFields`, `normalizeNeyviaChatActivitySegments`, `normalizeNeyviaChatStreamToolCalls`, `startNeyviaChatStreamPoll`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e.chat.normalizedCalls`, `proofs-e.chat.pollDelivery`, `proofs-e.chat.streamState`, `proofs-e.chat.streamTransition`, `proofs-e.chat.trace`.
- **Dependencies:** [surface.neyviaChatContracts](../surface.neyviaChatContracts/README.md).
- **Owner:** Neyvia / neyviaChatStream.
- **Files:** [web/src/neyvia/neyviaChatStream.js](../../web/src/neyvia/neyviaChatStream.js).
