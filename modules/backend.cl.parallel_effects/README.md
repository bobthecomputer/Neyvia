# parallel_effects

Subject-bound Parallel effects: reread durable state, broker runs and Git.

- **Public API:** `checks_for`, `readonly`, `snapshot_for`, `verify`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.clean-start`, `parallel.committed-done`, `parallel.failed-start-settle`, `parallel.finish-authority`, `parallel.mod-worker-done`, `parallel.ordered-conflict`, `parallel.orphan-settle`, `parallel.question-answer`, `parallel.resolution`, `parallel.safe-settle`, `parallel.separate-worktrees`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.cl.effects](../backend.cl.effects/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cl/parallel_effects.py](../../src/grant_agent/cl/parallel_effects.py).
