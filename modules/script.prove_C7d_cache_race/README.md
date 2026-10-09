# prove_C7d_cache_race

Real mission/cache calls plus unchanged-state checks at the production boundary.

- **Public API:** `main`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.durability](../backend.durability/README.md), [backend.edge_contracts](../backend.edge_contracts/README.md), [backend.edge_fixture_c7d_control](../backend.edge_fixture_c7d_control/README.md), [backend.mission_control](../backend.mission_control/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md), [backend.proof_credential_guard](../backend.proof_credential_guard/README.md), [backend.proof_ports](../backend.proof_ports/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/prove_C7d_cache_race.py](../../scripts/prove_C7d_cache_race.py).
