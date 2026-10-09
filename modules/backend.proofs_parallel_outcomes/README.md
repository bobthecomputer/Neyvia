# proofs_parallel_outcomes

Real Git/worktree lifecycle with confined local session transport.

- **Public API:** `availability`, `committed`, `film_native`, `lifecycle`, `recovery`, `repository`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `parallel.availability-retry`, `parallel.clean-start`, `parallel.committed-done`, `parallel.failed-start-settle`, `parallel.finish-authority`, `parallel.mod-worker-done`, `parallel.ordered-conflict`, `parallel.orphan-settle`, `parallel.pending-question-retry`, `parallel.question-answer`, `parallel.resolution`, `parallel.safe-settle`, `parallel.separate-worktrees`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.connected_sessions.__init__](../backend.connected_sessions.__init__/README.md), [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.neyvia_parallel_git](../backend.neyvia_parallel_git/README.md), [backend.proofs_local_session_fixture](../backend.proofs_local_session_fixture/README.md), [backend.proofs_rel29_outcomes](../backend.proofs_rel29_outcomes/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_parallel_outcomes.py](../../src/grant_agent/proofs_parallel_outcomes.py).
