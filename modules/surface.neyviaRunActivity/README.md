# neyviaRunActivity

Provides safeReceiptHref, runDurationLabel, visibleRunActivityEvents, presentRunActivity for Neyvia's UI state and behavior.

- **Public API:** `presentRunActivity`, `runDurationLabel`, `safeReceiptHref`, `visibleRunActivityEvents`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `activity.duration`, `activity.href`, `proofs-e.chat.activity`, `proofs-e.chat.visibleActivity`.
- **Dependencies:** [surface.neyviaChatContracts](../surface.neyviaChatContracts/README.md), [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md), [surface.neyviaToolVisuals](../surface.neyviaToolVisuals/README.md).
- **Owner:** Neyvia / neyviaRunActivity.
- **Files:** [web/src/neyvia/neyviaRunActivity.js](../../web/src/neyvia/neyviaRunActivity.js).
