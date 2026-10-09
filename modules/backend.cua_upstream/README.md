# cua_upstream

Private, process-owned MIT Cua Driver runtime; no global installation or daemon.

- **Public API:** `UpstreamDriver`, `checkout_runtime`, `install_runtime`, `runtime_candidates`, `runtime_directory`, `runtime_status`, `shared_runtime`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `cua.helper-resolution`.
- **Dependencies:** [backend.mcp_broker](../backend.mcp_broker/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/cua_upstream.py](../../src/grant_agent/cua_upstream.py).
