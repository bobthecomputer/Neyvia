# neyviaToolCallPresentation

Provides readJsonStringField, repairUtf16Text, toolFamily, parseUnifiedDiff for Neyvia's UI state and behavior.

- **Public API:** `commandOutputSummary`, `parseUnifiedDiff`, `presentToolCall`, `readJsonStringField`, `repairUtf16Text`, `toolFamily`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e.chat.commandSummary`, `proofs-e.chat.diff`, `proofs-e.chat.family`, `proofs-e.chat.presentation`, `proofs-e.chat.stringField`, `proofs-e.chat.utf16`.
- **Dependencies:** [surface.neyviaChatContracts](../surface.neyviaChatContracts/README.md).
- **Owner:** Neyvia / neyviaToolCallPresentation.
- **Files:** [web/src/neyvia/neyviaToolCallPresentation.js](../../web/src/neyvia/neyviaToolCallPresentation.js).
