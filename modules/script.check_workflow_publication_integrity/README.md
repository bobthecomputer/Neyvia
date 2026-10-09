# check_workflow_publication_integrity

Fail closed when GitHub Actions can silently mutate NEYVIA publication state.

- **Public API:** `audit_workflows`, `main`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `adapters.workflow.publication`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/check_workflow_publication_integrity.py](../../scripts/check_workflow_publication_integrity.py).
