# proofs_connections

Pure cases for the connections screen's invariants (track CONN): no process, network or credential is touched.

- **Public API:** `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `conn.install.lifecycle`, `conn.screen.invariants`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.contract_gate](../backend.contract_gate/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_connections.py](../../src/grant_agent/proofs_connections.py).
