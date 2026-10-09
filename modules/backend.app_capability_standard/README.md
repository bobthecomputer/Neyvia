# app_capability_standard

Provides backend / app_capability_standard in Neyvia.

- **Public API:** `build_connected_apps_snapshot`, `load_mock_manifests`, `manifest_schema`, `validate_handshake_payload`, `validate_manifest_payload`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a.app-cloud`, `a.app-observation`, `a.app-state`, `a.app-storage`.
- **Dependencies:** [backend.application_surface](../backend.application_surface/README.md), [backend.durability](../backend.durability/README.md), [backend.models](../backend.models/README.md), [backend.proofs_a_app_standard](../backend.proofs_a_app_standard/README.md), [backend.proofs_a_capabilities](../backend.proofs_a_capabilities/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/app_capability_standard.py](../../src/grant_agent/app_capability_standard.py).
