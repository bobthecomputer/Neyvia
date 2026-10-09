# neyvia_onboarding

First run: base pack download, runtime detection, interests and the tour.

- **Public API:** `PackUnavailableError`, `base_pack_status`, `call_tool`, `detect_runtimes`, `handle`, `install_pack`, `load_catalog`, `load_manifest`, `load_pack_manifest`, `main`, `manifest_source`, `pack_status`, `parse_manifest`, `pause_base_pack`, `read_state`, `recommend`, `run_download`, `save_state`, `snapshot`, `start_base_pack`, `tool_specs`, `tour_seconds`, `neyvia.onboarding.base_pack`, `neyvia.onboarding.open`, `neyvia.onboarding.pack`, `neyvia.onboarding.recommend`, `neyvia.onboarding.runtimes`, `neyvia.onboarding.save`, `neyvia.onboarding.state`.
- **Manual:** [local-rendering.cl](../../manuals/cl/local-rendering.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [onboarding.cl](../../manuals/cl/onboarding.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `onboarding.addon-isolation`, `onboarding.addon-recovery`, `onboarding.catalog-integrity`, `onboarding.choices-durable`, `onboarding.manifest-safety`, `onboarding.ordered-recommendations`, `onboarding.pause`, `onboarding.resume-reuse`, `onboarding.signature-authority`, `onboarding.verified-staging`, `p22.installer.local-pack-journey`, `p22.onboarding.external-source-readiness`, `p22.onboarding.first-run-snapshot`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.harness_registry](../backend.harness_registry/README.md), [backend.install_profiles](../backend.install_profiles/README.md), [backend.proofs_d_onboarding](../backend.proofs_d_onboarding/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / local-rendering.
- **Files:** [src/grant_agent/neyvia_onboarding.py](../../src/grant_agent/neyvia_onboarding.py).
