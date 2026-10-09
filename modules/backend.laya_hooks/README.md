# laya_hooks

Small, self-contained hooks that put LAYA's learned decisions in front of the big model.

- **Public API:** `candidate_layer`, `decide`, `laya_ready`, `learn_outcome`, `learn_route`, `load_vocab`, `page_done_state`, `route_layer`, `route_state`, `select_memory`, `taste_state`, `tokens`, `triage_taste`, `verify`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.laya_curriculum](../backend.laya_curriculum/README.md), [backend.laya_host](../backend.laya_host/README.md), [backend.laya_instant](../backend.laya_instant/README.md), [backend.laya_instant_ingest](../backend.laya_instant_ingest/README.md), [backend.laya_ledger](../backend.laya_ledger/README.md), [backend.laya_outcomes](../backend.laya_outcomes/README.md), [backend.laya_service](../backend.laya_service/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/laya_hooks.py](../../src/grant_agent/laya_hooks.py).
