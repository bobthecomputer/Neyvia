# turn_compartment

Persist a chat turn's runtime compartment as its own data plus a reference.

- **Public API:** `as_checkpoint`, `as_delta`, `delta_messages`, `for_storage`, `has_full_window`, `history_marker`, `hydrate`, `is_delta`, `legacy_as_delta`, `rebuild_window`, `window_digest`, `without_window`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.chat-storage-compaction-outcome`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/turn_compartment.py](../../src/grant_agent/turn_compartment.py).
