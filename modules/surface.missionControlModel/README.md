# missionControlModel

Provides parseWorkspaceSyncConflictBatchResolutions, parseWorkspaceSyncStatus, deriveProjectProgressHistory, deriveWorkspaceHealth for Neyvia's UI state and behavior.

- **Public API:** `buildMissionControlModel`, `buildRecentRuns`, `deriveMissionContextRoots`, `deriveProjectProgressHistory`, `deriveSubAgentLanes`, `deriveWorkspaceHealth`, `parseWorkspaceSyncConflictBatchResolutions`, `parseWorkspaceSyncStatus`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-reference.cl](../../manuals/cl/neyvia-reference.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `mission.review.projection`.
- **Dependencies:** [surface.missionHelpers](../surface.missionHelpers/README.md), [surface.missionReviewContracts](../surface.missionReviewContracts/README.md).
- **Owner:** Neyvia / missionControlModel.
- **Files:** [web/src/neyvia/missionControlModel.js](../../web/src/neyvia/missionControlModel.js).
