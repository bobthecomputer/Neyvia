# agent_submission_gate

Read-only validation for immutable agent-submission receipts.

- **Public API:** `GateResult`, `validate_receipt`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.submission-counts`, `control.submission-git-delta`, `control.submission-lineage`, `control.submission-secrets`, `control.submission-source-phase`, `control.submission-verdict`.
- **Dependencies:** [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/agent_submission_gate.py](../../src/grant_agent/agent_submission_gate.py).
