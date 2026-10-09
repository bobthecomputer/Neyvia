# imageProviderAdapters

Provides QUEUE_TIMELINE_STAGES, IMAGE_PROVIDER_ADAPTERS, buildIssueThreadRef, snapshotOverlayAnnotations for Neyvia's UI state and behavior.

- **Public API:** `IMAGE_PROVIDER_ADAPTERS`, `QUEUE_TIMELINE_STAGES`, `applyProviderResult`, `buildIssueThreadRef`, `buildQueueTimeline`, `createLocalDraftResult`, `getProviderAdapter`, `registerImageProviderAdapter`, `snapshotOverlayAnnotations`.
- **Manual:** [image-studio.cl](../../manuals/cl/image-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `image.generate.deadline`, `image.provider.adapter`, `image.provider.history`, `image.provider.receipt`, `image.queue.failed-timeline`.
- **Dependencies:** [surface.imagePlaygroundContracts](../surface.imagePlaygroundContracts/README.md), [surface.imagePlaygroundState](../surface.imagePlaygroundState/README.md).
- **Owner:** Neyvia / imageProviderAdapters.
- **Files:** [web/src/neyvia/imageProviderAdapters.js](../../web/src/neyvia/imageProviderAdapters.js).
