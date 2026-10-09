# neyvia_missions

Mission metadata and branch supervision over the existing Night Shift engine.

- **Public API:** `admission`, `call`, `control`, `create`, `initialize`, `records`, `remaining_limits`, `summary`, `usage`, `neyvia.mission.control`, `neyvia.mission.create`, `neyvia.mission.from_plan`, `neyvia.mission.list`.
- **Manual:** [mission-plan.cl](../../manuals/cl/mission-plan.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [neyvia-reference.cl](../../manuals/cl/neyvia-reference.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.neyvia_mission_plan](../backend.neyvia_mission_plan/README.md), [backend.neyvia_runtime](../backend.neyvia_runtime/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.nightshift_resources](../backend.nightshift_resources/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / mission-plan.
- **Files:** [src/grant_agent/neyvia_missions.py](../../src/grant_agent/neyvia_missions.py).
