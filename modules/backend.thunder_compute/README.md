# thunder_compute

Work with the user's existing Thunder Compute account through connected Chrome.

- **Public API:** `ConsoleReading`, `ThunderComputeError`, `execute_neyvia_proposal`, `execute_proposal`, `find_console_tab`, `load_project_memory`, `open_console`, `project_memory_path`, `propose_action`, `read_console`, `save_project_memory`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.chrome-live-action`, `control.console-memory`, `control.console-observation`, `control.neyvia-live-action`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.neyvia_browser](../backend.neyvia_browser/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/thunder_compute.py](../../src/grant_agent/thunder_compute.py).
