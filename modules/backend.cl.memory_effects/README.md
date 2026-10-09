# memory_effects

CL memory mutations require exact fresh scoped owner postconditions.

- **Public API:** `checks_for`, `owner`, `readonly`, `snapshot_for`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cue_memory](../backend.cue_memory/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cl/memory_effects.py](../../src/grant_agent/cl/memory_effects.py).
