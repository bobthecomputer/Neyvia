# browser_preflight

Provides backend / browser_preflight in Neyvia.

- **Public API:** `build_browser_dependency_preflight`, `repair_browser_dependencies`, `write_browser_dependency_preflight`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.browser-preflight`, `control.browser-repair`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/browser_preflight.py](../../src/grant_agent/browser_preflight.py).
