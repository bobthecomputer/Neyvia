# codex_rpc

One long-lived ``codex app-server`` JSON-RPC connection over stdio.

- **Public API:** `AppServerConnection`, `CodexError`, `ConnectionLost`, `RpcError`, `RpcTimeout`, `kill_process_tree`, `resolve_command`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `providers.process.hidden`, `providers.rpc.backoff`, `providers.rpc.response`.
- **Dependencies:** [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.proofs_a_providers](../backend.proofs_a_providers/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/connected_sessions/codex_rpc.py](../../src/grant_agent/connected_sessions/codex_rpc.py).
