# proof_readiness

Startup readiness runs only the changed Connected Language contracts.

- **Public API:** `failing_claims`, `run_now`, `skipped_claims`, `start_background`, `status`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs.background-readiness`.
- **Dependencies:** [backend.contract_gate](../backend.contract_gate/README.md), [backend.durability](../backend.durability/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_readiness.py](../../src/grant_agent/proof_readiness.py).
