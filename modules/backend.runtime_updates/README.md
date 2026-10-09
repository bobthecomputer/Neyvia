# runtime_updates

Provides backend / runtime_updates in Neyvia.

- **Public API:** `compare_version_tokens`, `latest_hermes_release`, `latest_npm_release`, `latest_openclaw_release`, `latest_opencode_release`, `normalize_hermes_version`, `normalize_openclaw_version`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [proofs.cl](../../manuals/cl/proofs.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.version.order`, `p22.release-parsing`.
- **Dependencies:** [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md).
- **Owner:** Neyvia / proofs.
- **Files:** [src/grant_agent/runtime_updates.py](../../src/grant_agent/runtime_updates.py).
