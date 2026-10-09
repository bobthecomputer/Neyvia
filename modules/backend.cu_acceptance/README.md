# cu_acceptance

Standalone structured Computer Use acceptance for N-E-Y-V-I-A.

- **Public API:** `CuAcceptanceRunner`, `compact_match_summary`, `control_preview_url`, `discover_base_urls`, `find_live_base_url`, `login_credentials_from_env`, `login_url`, `main`, `probe_http`, `receipt_dir`, `repo_root`, `run_flow`, `run_suite`, `skip_reason_no_server`, `write_receipt`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.cu-aliases`, `control.cu-receipt`, `control.cu-recovery`, `control.cu-verdict`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.ui_tools](../backend.ui_tools/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cu_acceptance.py](../../src/grant_agent/cu_acceptance.py).
