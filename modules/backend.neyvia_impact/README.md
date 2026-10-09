# neyvia_impact

Impact map: given changed files, list what they connect to, and what is broken in the wiring today.

- **Public API:** `find_gaps`, `impact`, `impact_enrichment`, `index`, `warm`.
- **Manual:** [awareness.cl](../../manuals/cl/awareness.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [tools-depth.cl](../../manuals/cl/tools-depth.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `awareness.impact.command`, `awareness.impact.gaps`, `impact.dispatch-membership`, `impact.import-provenance`, `impact.index-provenance`, `impact.ui-call-evidence`.
- **Dependencies:** [backend.proofs_awareness](../backend.proofs_awareness/README.md), [backend.proofs_e_release](../backend.proofs_e_release/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / awareness.
- **Files:** [src/grant_agent/neyvia_impact.py](../../src/grant_agent/neyvia_impact.py).
