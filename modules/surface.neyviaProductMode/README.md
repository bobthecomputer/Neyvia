# neyviaProductMode

Provides PRODUCT_MODE_CHAT, PRODUCT_MODE_ORCHESTRATION, PRODUCT_MODE_STORAGE_KEY, MANAGED_CLI_RUNTIME_OPTIONS for Neyvia's UI state and behavior.

- **Public API:** `LEAD_WORKERS_PRESET_ID`, `MANAGED_CLI_RUNTIME_DEFAULT_ROUTES`, `MANAGED_CLI_RUNTIME_OPTIONS`, `OTHER_RUNTIME_OPTIONS`, `PRODUCT_MODE_CHAT`, `PRODUCT_MODE_ORCHESTRATION`, `PRODUCT_MODE_STORAGE_KEY`, `RED_TEAM_ROLE_OPTIONS`, `RED_TEAM_SKILL_PACKS`, `buildDefaultOrchestrationRoles`, `buildLeadWorkersRoles`, `classifyLiveActionRows`, `mergeRuntimePickerOptions`, `normalizeProductMode`, `productModeToSurface`, `resolveOrchestrationRoles`, `runtimeFamilyForId`, `summarizeEventTimeline`, `summarizeMissionCard`, `surfaceToProductMode`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `batch.runtime-options`, `orchestration.preset`, `orchestration.resolve`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md), [surface.neyviaPresentationContracts](../surface.neyviaPresentationContracts/README.md).
- **Owner:** Neyvia / neyviaProductMode.
- **Files:** [web/src/neyvia/neyviaProductMode.js](../../web/src/neyvia/neyviaProductMode.js).
