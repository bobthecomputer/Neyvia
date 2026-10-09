# capability_catalog

Capability-pack catalog, fast routing, and deterministic plan compiler.

- **Public API:** `CapabilityPlanner`, `CapabilityRegistry`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a.capability-plan`, `a.catalog-adapter`, `a.catalog-observer`, `a.catalog-routing`, `p22.capability-config.adapter-refusal`, `p22.capability-config.search-plan`.
- **Dependencies:** [backend.capability_adapters](../backend.capability_adapters/README.md), [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.capability_runtime](../backend.capability_runtime/README.md), [backend.proofs_a_capabilities](../backend.proofs_a_capabilities/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/capability_catalog.py](../../src/grant_agent/capability_catalog.py).
