# neyviaMissionProjection

Provides NEYVIA_MISSION_PROJECTION_SCHEMA, MISSION_EVENT_WINDOW, missionIdOf, missionEventId for Neyvia's UI state and behavior.

- **Public API:** `MISSION_EVENT_WINDOW`, `NEYVIA_MISSION_PROJECTION_COMMANDS`, `NEYVIA_MISSION_PROJECTION_SCHEMA`, `acquireMissionSubscription`, `applyMissionEventDelta`, `buildMissionHandoff`, `buildSupervisoryReturn`, `createMissionProjectionStore`, `createMissionRecord`, `mergeMissionArtifacts`, `mergeMissionDetail`, `mergeMissionSummaries`, `missionEventCursor`, `missionEventId`, `missionIdOf`, `missionSubscriberCount`, `normalizeArtifactDescriptor`, `normalizeMissionEvent`, `projectAgentLiveView`, `projectBuilderRow`, `projectBuilderRows`, `projectMissionTimeline`, `releaseMissionSubscription`, `selectMissionRecord`.
- **Manual:** [mission-plan.cl](../../manuals/cl/mission-plan.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `mission.artifacts`, `mission.delta`, `mission.live`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / neyviaMissionProjection.
- **Files:** [web/src/neyvia/neyviaMissionProjection.js](../../web/src/neyvia/neyviaMissionProjection.js).
