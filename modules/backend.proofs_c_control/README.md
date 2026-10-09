# proofs_c_control

Control-room action invariants and local, durable manual self-checks.

- **Public API:** `cadence_healthy`, `capture`, `check`, `check_projection`, `checked`, `exhausted`, `extended_self_check`, `require`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-c.control.attachment`, `proofs-c.control.budget`, `proofs-c.control.cache`, `proofs-c.control.delete`, `proofs-c.control.events`, `proofs-c.control.evidence`, `proofs-c.control.git-actions`, `proofs-c.control.goal-audit`, `proofs-c.control.harness-summary`, `proofs-c.control.images`, `proofs-c.control.loss-audit`, `proofs-c.control.mission-counts`, `proofs-c.control.mission-loop`, `proofs-c.control.mode`, `proofs-c.control.notifications`, `proofs-c.control.overnight`, `proofs-c.control.preview`, `proofs-c.control.progress`, `proofs-c.control.proof-digest`, `proofs-c.control.queue`, `proofs-c.control.release-quality`, `proofs-c.control.replace-lock`, `proofs-c.control.route-trust`, `proofs-c.control.scope`, `proofs-c.control.storage-triage`, `proofs-c.control.title`, `proofs-c.control.validation-actions`, `proofs-c.control.verification`, `proofs-c.control.workspace-queue`, `proofs-c.control.workspaces`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.mission_control](../backend.mission_control/README.md), [backend.models](../backend.models/README.md), [backend.proof_contracts](../backend.proof_contracts/README.md), [backend.proof_ports](../backend.proof_ports/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_c_control.py](../../src/grant_agent/proofs_c_control.py).
