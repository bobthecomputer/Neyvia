# ios_studio

Provides backend / ios_studio in Neyvia.

- **Public API:** `create_ios_app`, `create_ios_build_capsule`, `inspect_ios_studio`, `load_ios_studio_config`, `probe_ios_builder`, `run_ios_build`, `save_ios_builder`, `start_ios_preview`, `stop_ios_preview`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-c.mobile.builder-config`, `proofs-c.mobile.bundle-id`, `proofs-c.mobile.capsule`, `proofs-c.mobile.project`, `proofs-c.mobile.scope`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_c_mobile](../backend.proofs_c_mobile/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.windows_ios_compiler](../backend.windows_ios_compiler/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/ios_studio.py](../../src/grant_agent/ios_studio.py).
