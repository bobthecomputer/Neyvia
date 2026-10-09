# neyvia_conductor

Goal planning and frozen routed DAGs on the existing detached Harness workers.

- **Public API:** `call`, `control_turn`, `execute`, `handle_command`, `request`, `neyvia.conductor.control`, `neyvia.conductor.get`, `neyvia.conductor.list`, `neyvia.conductor.plan`.
- **Manual:** [conductor.cl](../../manuals/cl/conductor.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connected_sessions.registry](../backend.connected_sessions.registry/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.neyvia_runtime](../backend.neyvia_runtime/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / conductor.
- **Files:** [src/grant_agent/neyvia_conductor.py](../../src/grant_agent/neyvia_conductor.py).
