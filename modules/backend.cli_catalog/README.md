# cli_catalog

Catalogue of optional CLIs, for the setup screen a nontechnical user sees.

- **Public API:** `CatalogEntry`, `build_catalog`, `classify`, `recommend`, `resolve_package_size`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a-cli.catalog.actions`, `a-cli.catalog.classify`, `a-cli.catalog.fact`, `a-cli.catalog.recommend`, `a-cli.catalog.selection`, `a-cli.catalog.size`.
- **Dependencies:** [backend.cli_installer](../backend.cli_installer/README.md), [backend.models](../backend.models/README.md), [backend.proofs_a_cli](../backend.proofs_a_cli/README.md), [backend.runtimes.__init__](../backend.runtimes.__init__/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cli_catalog.py](../../src/grant_agent/cli_catalog.py).
