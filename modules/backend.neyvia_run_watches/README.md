# neyvia_run_watches

One-shot run watches using the existing scheduler and broker state events.

- **Public API:** `call`, `evaluate`, `rows`, `neyvia.watch.cancel`, `neyvia.watch.create`, `neyvia.watch.list`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [neyvia-reference.cl](../../manuals/cl/neyvia-reference.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.watch-pages`.
- **Dependencies:** [backend.neyvia_time_tools](../backend.neyvia_time_tools/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia-core.
- **Files:** [src/grant_agent/neyvia_run_watches.py](../../src/grant_agent/neyvia_run_watches.py).
