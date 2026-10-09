# ui_graph

Resident browser UI graph: normalized nodes, revisions, semantic hash, compact deltas.

- **Public API:** `Bounds`, `UiDelta`, `UiGraph`, `UiNode`, `compute_semantic_hash`, `diff_graphs`, `find_nodes`, `format_compact_delta`, `format_compact_get`, `format_compact_listing`, `infer_actions`, `stable_node_id`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `sv.ui.compact-delta`, `sv.ui.delta`, `sv.ui.graph-state`, `sv.ui.query`, `sv.ui.semantic-identity`.
- **Dependencies:** [backend.proofs_e_sv](../backend.proofs_e_sv/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/ui_graph.py](../../src/grant_agent/ui_graph.py).
