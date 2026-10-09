# p2p_cache

Local-first BLAKE3 object cache prepared for an Iroh peer transport.

- **Public API:** `P2PCacheService`, `shutdown_p2p_sessions`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.cache.bootstrap`, `d.runtime.cache.compatibility`, `d.runtime.cache.import`, `d.runtime.cache.plan`, `d.runtime.cache.read`.
- **Dependencies:** [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.durability](../backend.durability/README.md), [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/p2p_cache.py](../../src/grant_agent/p2p_cache.py).
