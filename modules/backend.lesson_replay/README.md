# lesson_replay

Bounded real task replay: model writes files; host owns executable measurements.

- **Public API:** `capture_task_manifest`, `digest`, `relative`, `replay`, `validate_manifest`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.autopilot_model](../backend.autopilot_model/README.md), [backend.cl_deliverables](../backend.cl_deliverables/README.md), [backend.durability](../backend.durability/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/lesson_replay.py](../../src/grant_agent/lesson_replay.py).
