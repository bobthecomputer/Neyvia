# nx_promote

Promote sandbox work (Neyvia-next) into the main working tree, gated and reversible.

- **Public API:** `apply`, `build_release`, `changed_paths`, `main`, `plan`, `restart_supervisor`, `rollback`, `run_gate`, `serve`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/nx_promote.py](../../scripts/nx_promote.py).
