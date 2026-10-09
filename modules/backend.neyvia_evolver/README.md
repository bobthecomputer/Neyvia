# neyvia_evolver

Workspace-scoped observation boundary for the frozen Evolver engine.

- **Public API:** `call`, `handle_command`, `job`, `start`, `state`, `neyvia.evolver.genome`, `neyvia.evolver.job`, `neyvia.evolver.lineage`, `neyvia.evolver.receipt`, `neyvia.evolver.run`, `neyvia.evolver.state`.
- **Manual:** [hill-climb.cl](../../manuals/cl/hill-climb.cl), [local-evolver.cl](../../manuals/cl/local-evolver.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.evolver_core](../backend.evolver_core/README.md), [backend.evolver_laya](../backend.evolver_laya/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.neyvia_settings](../backend.neyvia_settings/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / hill-climb.
- **Files:** [src/grant_agent/neyvia_evolver.py](../../src/grant_agent/neyvia_evolver.py).
