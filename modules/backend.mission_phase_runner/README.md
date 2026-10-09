# mission_phase_runner

Provides backend / mission_phase_runner in Neyvia.

- **Public API:** `MissionPhaseTransition`, `MissionPhaseTransitionError`, `complete_current_phase`, `start_current_phase`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-c.missions.phase-transition`, `proofs-c.missions.run-envelope`.
- **Dependencies:** [backend.models](../backend.models/README.md), [backend.proofs_c_missions](../backend.proofs_c_missions/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/mission_phase_runner.py](../../src/grant_agent/mission_phase_runner.py).
