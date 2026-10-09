# neyvia_agentview

Agent view: watch and steer agents working on their own surfaces.

- **Public API:** `AgentView`, `AgentViewContractError`, `Frame`, `Run`, `Surface`, `SurfaceFrames`, `attach_browser_feedback`, `browser_event`, `changed_tiles`, `contract`, `data_url`, `delta_holds`, `describe`, `element_at`, `encode_jpeg`, `existing`, `fit`, `norm_box`, `now_iso`, `request`, `run_key`, `safe_key`, `serve_http`, `thin_keyframes`, `tile_rects`, `view_for`, `neyvia.agentview.check`, `neyvia.agentview.state`.
- **Manual:** [agent-view.cl](../../manuals/cl/agent-view.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `agentview.bounds`, `agentview.delta`, `agentview.demand`, `agentview.feedback`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.__init__](../backend.connected_sessions.__init__/README.md), [backend.durability](../backend.durability/README.md), [backend.neyvia_cua](../backend.neyvia_cua/README.md), [backend.neyvia_remote](../backend.neyvia_remote/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / agent-view.
- **Files:** [src/grant_agent/neyvia_agentview.py](../../src/grant_agent/neyvia_agentview.py).
