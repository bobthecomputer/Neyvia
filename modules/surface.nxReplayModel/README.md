# nxReplayModel

Provides SPEEDS, IDLE_CAP_MS, buildTimeline, visibleCount for Neyvia's UI state and behavior.

- **Public API:** `IDLE_CAP_MS`, `SPEEDS`, `buildTimeline`, `formatSpan`, `playbackMs`, `recordedAt`, `timelineMarks`, `visibleCount`.
- **Manual:** [agents.cl](../../manuals/cl/agents.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `replay.buildTimeline`, `replay.formatSpan`, `replay.playbackMs`, `replay.recordedAt`, `replay.timelineMarks`, `replay.visibleCount`.
- **Dependencies:** [surface.nxProofsEContracts](../surface.nxProofsEContracts/README.md).
- **Owner:** Neyvia / nxReplayModel.
- **Files:** [web/src/neyvia/next/nxReplayModel.js](../../web/src/neyvia/next/nxReplayModel.js).
