# onboarding

Provides backend / onboarding in Neyvia.

- **Public API:** `build_guidance_snapshot`, `detect_onboarding_status`, `detect_wsl_status`, `invalidate_onboarding_status_cache`, `load_telegram_destination`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.models](../backend.models/README.md), [backend.profiles](../backend.profiles/README.md), [backend.progressive_setup](../backend.progressive_setup/README.md), [backend.runtime_updates](../backend.runtime_updates/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md), [backend.runtimes.openclaw](../backend.runtimes.openclaw/README.md), [backend.snapshot_cache](../backend.snapshot_cache/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/onboarding.py](../../src/grant_agent/onboarding.py).
