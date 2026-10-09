# proofs_surface_games_extra

Game Dev's typed screen-selection state survives backend readback and rejects invalid tabs without overwriting it.

- **Public API:** `screen_state_persists_and_refuses_invalid_tab`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.gamedev.screen-state-persistence`.
- **Dependencies:** [backend.contract_gate](../backend.contract_gate/README.md), [backend.neyvia_gamedev](../backend.neyvia_gamedev/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_surface_games_extra.py](../../src/grant_agent/proofs_surface_games_extra.py).
