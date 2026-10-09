# imagePlaygroundContracts

Provides ImageContractError, IMAGE_CONTRACTS, checkedImageAction, checkImagePromptPresets for Neyvia's UI state and behavior.

- **Public API:** `IMAGE_CONTRACTS`, `ImageContractError`, `checkImagePromptPresets`, `checkedImageAction`.
- **Manual:** [image-studio.cl](../../manuals/cl/image-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `image.history.annotations`, `image.history.focus`, `image.history.thread`, `image.keyboard.announcement`, `image.keyboard.entry`, `image.keyboard.tooltip`, `image.keyboard.trail`, `image.layers.delete`, `image.layers.selection`, `image.layers.update`, `image.payload.geometry`, `image.prompt.presets`, `image.provider.adapter`, `image.provider.history`, `image.provider.receipt`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / imagePlaygroundContracts.
- **Files:** [web/src/neyvia/imagePlaygroundContracts.js](../../web/src/neyvia/imagePlaygroundContracts.js).
