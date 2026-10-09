# nxBus

Provides busClientId, approveUiRequest, ackPane, subscribeTimers for Neyvia's UI state and behavior.

- **Public API:** `ackPane`, `ackTimer`, `approveUiRequest`, `busClientId`, `deliver`, `isReplay`, `listMissions`, `missionRequest`, `reportAppState`, `sessionAction`, `startBus`, `subscribeTimers`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [surface.nxApi](../surface.nxApi/README.md), [surface.nxBusMock](../surface.nxBusMock/README.md), [surface.nxOsStore](../surface.nxOsStore/README.md), [surface.nxSettingsApi](../surface.nxSettingsApi/README.md), [surface.nxShellObserve](../surface.nxShellObserve/README.md).
- **Owner:** Neyvia / nxBus.
- **Files:** [web/src/neyvia/next/nxBus.js](../../web/src/neyvia/next/nxBus.js).
