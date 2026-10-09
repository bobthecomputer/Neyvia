# neyvia_autopilot

Intent-driven execution using grounded manuals, checks and compiled evidence.

- **Public API:** `ManualSelectionError`, `call`, `catalog`, `checked_selection`, `completed_response`, `decode_selection`, `execute`, `explore`, `forward_command`, `launch`, `learn_completed`, `learn_journey`, `load`, `model`, `obj`, `replay_completed`, `request`, `resolve_manual_id`, `save`, `selection_model`, `state_lock`, `state_path`, `stopped`, `storage`, `verify_app_goal`, `neyvia.autopilot.get`, `neyvia.autopilot.list`, `neyvia.autopilot.resume`, `neyvia.autopilot.start`, `neyvia.autopilot.stop`.
- **Manual:** [autopilot.cl](../../manuals/cl/autopilot.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `autopilot.live-manual-selection`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.autopilot_model](../backend.autopilot_model/README.md), [backend.durability](../backend.durability/README.md), [backend.efficiency_cascade](../backend.efficiency_cascade/README.md), [backend.manual_compiler](../backend.manual_compiler/README.md), [backend.manual_state](../backend.manual_state/README.md), [backend.manual_versions](../backend.manual_versions/README.md), [backend.native_access](../backend.native_access/README.md), [backend.neyvia_agent](../backend.neyvia_agent/README.md), [backend.neyvia_app_sdk](../backend.neyvia_app_sdk/README.md), [backend.neyvia_awareness](../backend.neyvia_awareness/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.transition_memory](../backend.transition_memory/README.md).
- **Owner:** Neyvia / autopilot.
- **Files:** [src/grant_agent/neyvia_autopilot.py](../../src/grant_agent/neyvia_autopilot.py).
