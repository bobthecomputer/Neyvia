# neyviaToolVisuals

Provides NEYVIA_APP_ICON_PATHS, NEYVIA_FILE_TYPE_VISUALS, NEYVIA_TOOL_PHASE_CLASSES, NEYVIA_PANEL_ENTER_CLASSES for Neyvia's UI state and behavior.

- **Public API:** `NEYVIA_APP_ICON_PATHS`, `NEYVIA_CHAT_TOOL_CATALOG`, `NEYVIA_FILE_TYPE_VISUALS`, `NEYVIA_LIBRARY_FILE_STUBS`, `NEYVIA_MANAGED_SUITE_CATALOG`, `NEYVIA_PANEL_ENTER_CLASSES`, `NEYVIA_TOOL_CATEGORY_ORDER`, `NEYVIA_TOOL_PHASE_CLASSES`, `NEYVIA_TOOL_VISUALS`, `getNeyviaFileTypeVisual`, `getNeyviaToolVisual`, `groupNeyviaChatToolsByCategory`, `humanizeNeyviaToolId`, `inferNeyviaToolPhase`, `isNeyviaToolEventChip`, `listNeyviaToolVisualIds`, `neyviaPanelEnterClass`, `neyviaToolChipClasses`, `neyviaToolPhaseLabel`, `resolveNeyviaMessageChip`, `resolveNeyviaToolId`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e.chat.chip`, `proofs-e.chat.phase`.
- **Dependencies:** [surface.neyviaChatContracts](../surface.neyviaChatContracts/README.md), [surface.neyviaToolVisualsInventory](../surface.neyviaToolVisualsInventory/README.md).
- **Owner:** Neyvia / neyviaToolVisuals.
- **Files:** [web/src/neyvia/neyviaToolVisuals.js](../../web/src/neyvia/neyviaToolVisuals.js).
