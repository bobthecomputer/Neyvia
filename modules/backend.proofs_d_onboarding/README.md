# proofs_d_onboarding

Onboarding semantic contracts and real disposable staging procedures.

- **Public API:** `check_catalog`, `check_download_result`, `check_manifest`, `check_pack_status`, `check_recommendation`, `check_saved`, `check_staged_file`, `check_staging_scope`, `require`, `safe_destination`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [onboarding.cl](../../manuals/cl/onboarding.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `onboarding.addon-isolation`, `onboarding.addon-recovery`, `onboarding.catalog-integrity`, `onboarding.choices-durable`, `onboarding.manifest-safety`, `onboarding.ordered-recommendations`, `onboarding.pause`, `onboarding.resume-reuse`, `onboarding.signature-authority`, `onboarding.verified-staging`, `p22.onboarding.external-source-readiness`, `p22.onboarding.first-run-snapshot`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.native_tools](../backend.native_tools/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.proof_ports](../backend.proof_ports/README.md).
- **Owner:** Neyvia / onboarding.
- **Files:** [src/grant_agent/proofs_d_onboarding.py](../../src/grant_agent/proofs_d_onboarding.py).
