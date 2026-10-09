# proofs_awareness

Work-board and impact-graph manual contracts checked by the local host.

- **Public API:** `after`, `before`, `check_command`, `check_gaps`, `check_list`, `check_overlap`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `awareness.claim.overlaps`, `awareness.claim.persisted`, `awareness.claim.refresh`, `awareness.claim.staleness`, `awareness.impact.command`, `awareness.impact.gaps`, `awareness.list.projection`, `awareness.paths.overlap`, `awareness.release.persisted`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.neyvia_awareness](../backend.neyvia_awareness/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_awareness.py](../../src/grant_agent/proofs_awareness.py).
