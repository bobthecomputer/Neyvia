# connections_install

Consented, hidden harness installation; progress and receipts share the Connections card.

- **Public API:** `command`, `environment`, `install`, `install_package`, `prerequisite`, `progress`, `run_hidden`, `update_installed`, `update_label`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `conn.install.lifecycle`.
- **Dependencies:** [backend.cli_installer](../backend.cli_installer/README.md), [backend.component_install](../backend.component_install/README.md), [backend.harness_auth_inventory](../backend.harness_auth_inventory/README.md), [backend.runtime_auto_update](../backend.runtime_auto_update/README.md), [backend.runtime_updates](../backend.runtime_updates/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connections_install.py](../../src/grant_agent/connections_install.py).
