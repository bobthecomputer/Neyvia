# harness_registry

Provides backend / harness_registry in Neyvia.

- **Public API:** `HarnessSpec`, `build_harness_catalog`, `discover_harness_context`, `harness_gateway_environment`, `merge_harness_launch_env`, `read_harness_instruction`, `resolve_harness_profile`, `runtime_picker_choices`, `save_harness_instruction`, `save_harness_profile`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-b.harness.catalog`, `proofs-b.harness.gateway`, `proofs-b.harness.instruction`, `proofs-b.harness.public-profile`.
- **Dependencies:** [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.neyvia_version](../backend.neyvia_version/README.md), [backend.proofs_b_harness](../backend.proofs_b_harness/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/harness_registry.py](../../src/grant_agent/harness_registry.py).
