# comments_effects

CL comments actions are checked against fresh immutable store events.

- **Public API:** `checks_for`, `readonly`, `snapshot_for`, `verify`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `comments.append-only`, `comments.send`.
- **Dependencies:** [backend.neyvia_comments](../backend.neyvia_comments/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cl/comments_effects.py](../../src/grant_agent/cl/comments_effects.py).
