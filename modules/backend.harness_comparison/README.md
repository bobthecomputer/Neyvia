# harness_comparison

Deterministic, receipt-backed comparison for installed Neyvia harnesses.

- **Public API:** `capability_coverage`, `eligibility`, `grade_output`, `parse_marked_result`, `select_leader`, `summarize_attempts`, `task_by_id`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `adapters.comparison.grading`, `adapters.comparison.leader`.
- **Dependencies:** [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/harness_comparison.py](../../src/grant_agent/harness_comparison.py).
