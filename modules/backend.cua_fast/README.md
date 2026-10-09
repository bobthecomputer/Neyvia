# cua_fast

Deadline-bounded native CUA. COM objects never leave their owning MTA lane.

- **Public API:** `DeadlineLane`, `FastClient`, `MsaaBackend`, `UiaBackend`, `UndispatchedTimeout`, `Win32`, `protected`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cua_fast.py](../../src/grant_agent/cua_fast.py).
