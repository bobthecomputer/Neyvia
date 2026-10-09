# night_mode

Provides backend / night_mode in Neyvia.

- **Public API:** `NightProductionProfile`, `build_morning_digest`, `build_night_readiness_receipt`, `build_production_night_profile`, `build_readiness_failure_message`, `classify_night_work`, `production_night_profile_payload`, `rank_night_queue`, `write_morning_digest`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d-ui.night-digest`, `d-ui.night-notification`, `d-ui.night-policy`, `d-ui.night-readiness`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.models](../backend.models/README.md), [backend.proofs_d_ui_planning](../backend.proofs_d_ui_planning/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/night_mode.py](../../src/grant_agent/night_mode.py).
