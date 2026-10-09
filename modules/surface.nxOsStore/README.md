# nxOsStore

Provides DENSITIES, PANE_KINDS, holdSettingsLook, initialOsState for Neyvia's UI state and behavior.

- **Public API:** `DENSITIES`, `PANE_KINDS`, `applyPrefs`, `applyUiAction`, `getLookVersions`, `getOs`, `holdSettingsLook`, `initialOsState`, `os`, `reduceUiAction`, `seedFromSnapshot`, `subscribeOs`, `useOs`, `withOverrides`.
- **Manual:** [design.cl](../../manuals/cl/design.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [sidebar.cl](../../manuals/cl/sidebar.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e.shell.initial`, `proofs-e.shell.overrides`, `proofs-e.shell.reducer`, `transparency.persistence`, `transparency.transition`.
- **Dependencies:** [surface.neyviaPresentationContracts](../surface.neyviaPresentationContracts/README.md), [surface.nxLayoutModel](../surface.nxLayoutModel/README.md), [surface.nxLookModel](../surface.nxLookModel/README.md), [surface.nxMorph](../surface.nxMorph/README.md), [surface.nxPaneObserve](../surface.nxPaneObserve/README.md), [surface.nxPlacementModel](../surface.nxPlacementModel/README.md), [surface.nxProofsEShellContracts](../surface.nxProofsEShellContracts/README.md), [surface.nxSidebarModel](../surface.nxSidebarModel/README.md), [surface.nxThemeRegistry](../surface.nxThemeRegistry/README.md), [surface.nxTransparencyModel](../surface.nxTransparencyModel/README.md).
- **Owner:** Neyvia / nxOsStore.
- **Files:** [web/src/neyvia/next/nxOsStore.js](../../web/src/neyvia/next/nxOsStore.js).
