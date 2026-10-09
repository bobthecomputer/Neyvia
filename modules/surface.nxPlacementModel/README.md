# nxPlacementModel

Provides PLACEMENTS, PLACEMENT_LABELS, MAX_BUBBLES, prefKey for Neyvia's UI state and behavior.

- **Public API:** `MAX_BUBBLES`, `PLACEMENTS`, `PLACEMENT_LABELS`, `closeWindow`, `dropZone`, `findWindow`, `mainDesc`, `moveBubble`, `normalizePrefs`, `openWindow`, `orderWithPanel`, `peekBubble`, `placeWindow`, `prefKey`, `rememberPlacement`, `restoreWindow`, `syncStage`, `windowAt`, `windowKey`.
- **Manual:** [design.cl](../../manuals/cl/design.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `placement.closeWindow`, `placement.dropZone`, `placement.moveBubble`, `placement.normalizePrefs`, `placement.openWindow`, `placement.orderWithPanel`, `placement.peekBubble`, `placement.placeWindow`, `placement.rememberPlacement`, `placement.restoreWindow`, `placement.syncStage`, `placement.windowKey`.
- **Dependencies:** [surface.nxProofsEContracts](../surface.nxProofsEContracts/README.md).
- **Owner:** Neyvia / nxPlacementModel.
- **Files:** [web/src/neyvia/next/nxPlacementModel.js](../../web/src/neyvia/next/nxPlacementModel.js).
