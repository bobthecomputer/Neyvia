# registry

Adapter registry for connected sessions, and the small calls around it.

- **Public API:** `ConnectedError`, `Registry`, `as_connected`, `bounded`, `describe`, `jsonable`, `make_session_id`, `normalize_app`, `parallel`, `parse_session_id`, `register_adapter`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.availability-retry`, `sessions.broker.refusals`, `sessions.broker.registry`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/registry.py](../../src/grant_agent/connected_sessions/registry.py).
