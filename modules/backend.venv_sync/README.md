# venv_sync

Keep Neyvia's managed Python environment in step with the bundled requirements.

- **Public API:** `installed_versions`, `main`, `pinned`, `read_marker`, `requirements_hash`, `status`, `sync`, `venv_python`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.component_install](../backend.component_install/README.md), [backend.durability](../backend.durability/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/venv_sync.py](../../src/grant_agent/venv_sync.py).
