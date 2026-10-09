# source_marketplace

Developer-source apps and mods on the existing marketplace catalog and host.

- **Public API:** `SourceMarketplace`, `authorize_app`, `handle_command`, `serve_sdk`, `neyvia.marketplace.get`, `neyvia.marketplace.install`, `neyvia.marketplace.list`, `neyvia.marketplace.read`, `neyvia.marketplace.remove`, `neyvia.marketplace.set`, `neyvia.marketplace.update`.
- **Manual:** [modules.cl](../../manuals/cl/modules.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.mod-lifecycle`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.cl.manuals](../backend.cl.manuals/README.md), [backend.durability](../backend.durability/README.md), [backend.module_marketplace](../backend.module_marketplace/README.md).
- **Owner:** Neyvia / modules.
- **Files:** [src/grant_agent/source_marketplace.py](../../src/grant_agent/source_marketplace.py).
