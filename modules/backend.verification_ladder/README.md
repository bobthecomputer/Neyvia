# verification_ladder

Provides backend / verification_ladder in Neyvia.

- **Public API:** `build_backend_command_smoke_receipt`, `build_changed_file_targeted_receipt`, `build_syntax_import_receipt`, `build_ui_button_smoke_receipt`, `build_verification_capacity_policy`, `build_verification_ladder`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sv.ladder.capacity`, `sv.ladder.plan`, `sv.ladder.receipt`.
- **Dependencies:** [backend.proofs_e_sv](../backend.proofs_e_sv/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/verification_ladder.py](../../src/grant_agent/verification_ladder.py).
