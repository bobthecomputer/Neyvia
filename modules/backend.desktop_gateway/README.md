# desktop_gateway

Provides backend / desktop_gateway in Neyvia.

- **Public API:** `load_desktop_gateway_heartbeats`, `load_gateway_events`, `reconcile_disappeared_gateway_jobs`, `record_desktop_gateway_heartbeat`, `record_gateway_event`, `route_gateway_job`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `desktop.gateway.event`, `desktop.gateway.heartbeat`, `desktop.gateway.reconcile`, `desktop.gateway.route`.
- **Dependencies:** [backend.cluster](../backend.cluster/README.md), [backend.models](../backend.models/README.md), [backend.proofs_b_desktop](../backend.proofs_b_desktop/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/desktop_gateway.py](../../src/grant_agent/desktop_gateway.py).
