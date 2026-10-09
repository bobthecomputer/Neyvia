# harness_auth_inventory

Secret-free, live authentication truth for Neyvia harnesses.

- **Public API:** `build_harness_auth_inventory`, `merge_auth_inventory`, `probe_timed_out`, `reset_probe_timeout`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.harness_runtime_inspection](../backend.harness_runtime_inspection/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/harness_auth_inventory.py](../../src/grant_agent/harness_auth_inventory.py).
