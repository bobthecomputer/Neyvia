# prune_C7e

Prune task-local redundant evidence after referenced observations are sealed.

- **Public API:** `add_reference_names`, `compact_observation`, `files_in`, `main`, `protected`, `refuse_credential_open`, `require_committed`, `retain_committed_references`, `text_references`, `validate_deadline`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.edge_fixture_catalog](../backend.edge_fixture_catalog/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/prune_C7e.py](../../scripts/prune_C7e.py).
