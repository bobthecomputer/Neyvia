# component_install

Shared staging, hashing and receipt helpers for Neyvia's managed components.

- **Public API:** `app_version`, `components_root`, `copy_tree`, `human_size`, `now`, `read_manifest`, `recover_dir`, `sha256_file`, `swap_dir`, `tree_files`, `tree_hash`, `unique_staging`, `verify_tree`, `write_manifest`, `write_receipt`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/component_install.py](../../src/grant_agent/component_install.py).
