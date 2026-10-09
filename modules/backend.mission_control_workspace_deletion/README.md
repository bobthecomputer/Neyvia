# mission_control_workspace_deletion

Recover scoped workspace deletion after a lost multi-file acknowledgement.

- **Public API:** `begin`, `complete`, `journal_path`, `recover`, `workspace_state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.durability](../backend.durability/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/mission_control_workspace_deletion.py](../../src/grant_agent/mission_control_workspace_deletion.py).
