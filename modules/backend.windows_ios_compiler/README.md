# windows_ios_compiler

Provides backend / windows_ios_compiler in Neyvia.

- **Public API:** `build_windows_ios_app`, `inspect_windows_ios_toolchain`, `install_windows_ios_toolchain`, `load_windows_ios_config`, `save_windows_ios_config`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-c.mobile.compiler-config`, `proofs-c.mobile.download-digest`, `proofs-c.mobile.error-text`, `proofs-c.mobile.metadata`, `proofs-c.mobile.package`, `proofs-c.mobile.web-assets`.
- **Dependencies:** [backend.apple_bundle](../backend.apple_bundle/README.md), [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_c_mobile](../backend.proofs_c_mobile/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/windows_ios_compiler.py](../../src/grant_agent/windows_ios_compiler.py).
