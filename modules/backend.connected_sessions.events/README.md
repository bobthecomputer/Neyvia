# events

The live stream's memory: a bounded ring of cursor-stamped events with blocking reads.

- **Public API:** `EventBuffer`, `bound_event`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.session-event-cursor`, `sessions.events.bounds`, `sessions.events.cursor`, `sessions.events.stamp`, `sessions.events.wait`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.registry](../backend.connected_sessions.registry/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/events.py](../../src/grant_agent/connected_sessions/events.py).
