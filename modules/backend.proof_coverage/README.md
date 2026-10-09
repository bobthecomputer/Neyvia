# proof_coverage

Reviewable test -> manual contract -> host check -> real receipt mapping.

- **Public API:** `coverage_source_current`, `evidence_revalidated`, `procedure_passed`, `record_coverage`, `render_map`, `retirement_gate`, `revalidate_coverage`, `revalidate_existing`, `revalidated_cases`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs.retirement-coverage`, `proofs.source-revalidation`.
- **Dependencies:** [backend.durability](../backend.durability/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_coverage.py](../../src/grant_agent/proof_coverage.py).
