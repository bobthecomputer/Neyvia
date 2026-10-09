# proof_ports

Explicit fixture port selection; sockets are never intercepted or remapped.

- **Public API:** `c7_port_block`, `c7_run_root`, `c7_worker_ports`, `configure_asyncio`, `configure_ports`, `proof_port`, `proof_text`, `selected_ports`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.asyncio-wakeup`.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proof_ports.py](../../src/grant_agent/proof_ports.py).
