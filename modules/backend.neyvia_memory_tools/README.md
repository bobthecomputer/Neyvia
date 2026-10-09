# neyvia_memory_tools

Authenticated Memory UI commands and the same scope-bound agent tools.

- **Public API:** `call`, `capture_outcome`, `chat_context`, `context_for_backend`, `handle_command`, `ingest_teaching`, `launcher_context`, `launcher_scope`, `operate`, `neyvia.memory.correct`, `neyvia.memory.forget`, `neyvia.memory.inspect`, `neyvia.memory.list`, `neyvia.memory.recall`, `neyvia.memory.remember`.
- **Manual:** [memory.cl](../../manuals/cl/memory.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `memory.launcher-host-binding`.
- **Dependencies:** [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.cue_memory](../backend.cue_memory/README.md), [backend.memory_recall](../backend.memory_recall/README.md).
- **Owner:** Neyvia / memory.
- **Files:** [src/grant_agent/neyvia_memory_tools.py](../../src/grant_agent/neyvia_memory_tools.py).
