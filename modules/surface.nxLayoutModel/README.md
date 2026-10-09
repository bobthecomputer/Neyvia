# nxLayoutModel

Provides REGIONS, REGION_LABELS, LIMITS, MAIN_MIN for Neyvia's UI state and behavior.

- **Public API:** `BUILTIN_SCENES`, `DEFAULT_LAYOUT`, `LIMITS`, `MAIN_COMFORT`, `MAIN_MIN`, `REGIONS`, `REGION_LABELS`, `WIDGETS`, `WIDGET_SPAN`, `addWidget`, `applyScene`, `captureScene`, `clampWidth`, `cycleWidgetSize`, `fitLayout`, `hiddenWidgets`, `keyWidth`, `moveRegion`, `moveWidget`, `normalizeLayout`, `nudgeRegion`, `nudgeWidget`, `removeWidget`, `resetWidth`, `sceneId`, `setRegionOrder`, `setWidth`, `sideOf`, `sizeLabel`.
- **Manual:** [design.cl](../../manuals/cl/design.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `layout.addWidget`, `layout.cycleWidgetSize`, `layout.fitLayout`, `layout.hiddenWidgets`, `layout.keyWidth`, `layout.moveRegion`, `layout.moveWidget`, `layout.normalizeLayout`, `layout.nudgeRegion`, `layout.nudgeWidget`, `layout.removeWidget`, `layout.setWidth`, `layout.sideOf`.
- **Dependencies:** [surface.nxProofsEContracts](../surface.nxProofsEContracts/README.md).
- **Owner:** Neyvia / nxLayoutModel.
- **Files:** [web/src/neyvia/next/nxLayoutModel.js](../../web/src/neyvia/next/nxLayoutModel.js).
