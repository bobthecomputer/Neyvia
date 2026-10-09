# native_resource_profiles

Resource-aware execution profiles for Neyvia Native.

- **Public API:** `NativeResourceProfile`, `detected_memory_mb`, `normalize_resource_mode`, `resolve_resource_profile`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.resources.admission`, `native.resources.mode`, `native.runtime.process-journey`.
- **Dependencies:** [backend.proofs_d_native](../backend.proofs_d_native/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/native_resource_profiles.py](../../src/grant_agent/native_resource_profiles.py).
