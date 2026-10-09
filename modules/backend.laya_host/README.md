# laya_host

The Neyvia backend owns the LAYA service: start it hidden, watch it, restart it, stop it with the backend.

- **Public API:** `LayaHost`, `current_url`, `host_for`, `instant_ready`, `load_config`, `mark_serving`, `restart`, `start`, `status`, `stop`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.laya_instant](../backend.laya_instant/README.md), [backend.laya_instant_ingest](../backend.laya_instant_ingest/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.taste_vision](../backend.taste_vision/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/laya_host.py](../../src/grant_agent/laya_host.py).
