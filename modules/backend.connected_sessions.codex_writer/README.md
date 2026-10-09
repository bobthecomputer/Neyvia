# codex_writer

Read-only probes of Codex's cross-process writer lock (never touch rollouts).

- **Public API:** `active_writer`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-e-host.writer`, `providers.codex.lock`.
- **Dependencies:** [backend.proofs_a_providers](../backend.proofs_a_providers/README.md), [backend.proofs_e_host](../backend.proofs_e_host/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/codex_writer.py](../../src/grant_agent/connected_sessions/codex_writer.py).
