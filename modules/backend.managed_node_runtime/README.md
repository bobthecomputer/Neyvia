# managed_node_runtime

Resolve a compatible per-user Node.js runtime for optional Neyvia CLIs.

- **Public API:** `ensure_openclaw_node_bin`, `managed_runtime_root`, `node_supports_current_openclaw`, `prepend_openclaw_node_to_env`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `runtime.node.environment`, `runtime.node.versions`.
- **Dependencies:** [backend.proofs_c_runtime](../backend.proofs_c_runtime/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/managed_node_runtime.py](../../src/grant_agent/managed_node_runtime.py).
