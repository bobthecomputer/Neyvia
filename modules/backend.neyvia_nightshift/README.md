# neyvia_nightshift

User, bot and desktop access to the existing durable Night Shift engine.

- **Public API:** `call`, `handle_command`, `request`, `respond`, `neyvia.nightshift.begin`, `neyvia.nightshift.block`, `neyvia.nightshift.create`, `neyvia.nightshift.edit`, `neyvia.nightshift.import`, `neyvia.nightshift.reparent`, `neyvia.nightshift.resources`, `neyvia.nightshift.start`, `neyvia.nightshift.stop`, `neyvia.nightshift.summary`, `neyvia.nightshift.task`, `neyvia.nightshift.tasks`, `neyvia.nightshift.tick`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [nightshift.cl](../../manuals/cl/nightshift.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.nightshift.local-policy-ui-journey`.
- **Dependencies:** [backend.nightshift](../backend.nightshift/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia-core.
- **Files:** [src/grant_agent/neyvia_nightshift.py](../../src/grant_agent/neyvia_nightshift.py).
