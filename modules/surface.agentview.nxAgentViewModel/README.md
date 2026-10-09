# nxAgentViewModel

Provides AgentViewContractError, MAX_LAYERS, POLL, QUIET_POLLS for Neyvia's UI state and behavior.

- **Public API:** `AgentViewContractError`, `ERROR_MS`, `IDLE_CAP_MS`, `MAX_LAYERS`, `POLL`, `QUIET_POLLS`, `SEGMENT_GAP_S`, `SEGMENT_STEPS`, `SPEEDS`, `applyFrame`, `awaySummary`, `boxPct`, `buildSegments`, `buildTimelapse`, `deliveryText`, `describeAction`, `emptyStack`, `feedbackPayload`, `fpsFor`, `layerStyle`, `mergeEntries`, `pointOnFrame`, `pollDelay`, `progressText`, `resultText`, `resultTone`, `rtAt`, `sinceFor`, `sizeClass`, `sizeText`, `spanText`, `stateAt`, `statusText`, `targetText`.
- **Manual:** [agent-view.cl](../../manuals/cl/agent-view.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `agentview.applyFrame`, `agentview.feedbackPayload`, `agentview.poll`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / nxAgentViewModel.
- **Files:** [web/src/neyvia/next/agentview/nxAgentViewModel.js](../../web/src/neyvia/next/agentview/nxAgentViewModel.js).
