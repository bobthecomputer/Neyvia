# cli_installer

Crash-aware per-user installer for optional npm-backed agent CLIs.

- **Public API:** `installer_status`, `installer_support`, `load_manifest`, `perform_cli_action`, `resolve_npm_release`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.installer.action`, `a-cli.installer.integrity`.
- **Dependencies:** [backend.cli_catalog](../backend.cli_catalog/README.md), [backend.durability](../backend.durability/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md), [backend.runtimes.base](../backend.runtimes.base/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cli_installer.py](../../src/grant_agent/cli_installer.py).
