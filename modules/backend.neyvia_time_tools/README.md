# neyvia_time_tools

Precise clocks and durable elapsed timers; timers never cancel agent work.

- **Public API:** `call`, `identity`, `label`, `measure`, `positive`, `stamp`, `view`, `neyvia.schedule.after`, `neyvia.time.budget`, `neyvia.time.now`, `neyvia.timer.lap`, `neyvia.timer.list`, `neyvia.timer.read`, `neyvia.timer.start`, `neyvia.timer.stop`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [neyvia-reference.cl](../../manuals/cl/neyvia-reference.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.timer-durable`.
- **Dependencies:** [backend.crashproof](../backend.crashproof/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_time_tools.py](../../src/grant_agent/neyvia_time_tools.py).
