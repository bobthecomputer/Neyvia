# imagePlaygroundState

Provides IMAGE_PLAYGROUND_STORAGE_KEY, CANVAS_SIZE_PRESETS, IMAGE_PROMPT_PRESETS, IMAGE_TOOL_DEFINITIONS for Neyvia's UI state and behavior.

- **Public API:** `CANVAS_SIZE_PRESETS`, `DEFAULT_IMAGE_PROJECT`, `IMAGE_PLAYGROUND_STORAGE_KEY`, `IMAGE_PROMPT_PRESETS`, `IMAGE_TOOL_DEFINITIONS`, `addHistoryEntry`, `appendKeyboardJumpTrail`, `buildKeyboardTraversalAnnouncement`, `createLayerFromSelection`, `createOpsThreadForFocusedHistory`, `formatKeyboardJumpTrailEntry`, `formatKeyboardJumpTrailTooltip`, `isRealImageSession`, `isRetiredSeed`, `keyboardScopeLabel`, `keyboardTraversalReasonLabel`, `loadImageProject`, `makeId`, `normalizeProject`, `nowIso`, `projectToProviderPayload`, `removeLayerFromProject`, `saveImageProject`, `setFocusedHistoryItem`, `settleStaleHistoryItem`, `structuredCloneSafe`, `updateFocusedHistoryAnnotations`, `updateLayerInProject`.
- **Manual:** [image-studio.cl](../../manuals/cl/image-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `image.generate.job-settled`, `image.history.annotations`, `image.history.focus`, `image.history.thread`, `image.keyboard.announcement`, `image.keyboard.entry`, `image.keyboard.tooltip`, `image.keyboard.trail`, `image.layers.delete`, `image.layers.selection`, `image.layers.update`, `image.payload.geometry`, `image.prompt.presets`.
- **Dependencies:** [surface.imagePlaygroundContracts](../surface.imagePlaygroundContracts/README.md).
- **Owner:** Neyvia / imagePlaygroundState.
- **Files:** [web/src/neyvia/imagePlaygroundState.js](../../web/src/neyvia/imagePlaygroundState.js).
