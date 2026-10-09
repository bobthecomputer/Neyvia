# runtime_capability_inventory

Small, secret-safe inventory for runtime tools, linked plugins, and MCP servers.

- **Public API:** `build_runtime_capability_inventory`.
- **Manual:** [awareness.cl](../../manuals/cl/awareness.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `runtime.capability-metadata`.
- **Dependencies:** [backend.codex_import](../backend.codex_import/README.md), [backend.codex_plugin_access](../backend.codex_plugin_access/README.md), [backend.codex_skill_access](../backend.codex_skill_access/README.md), [backend.hermes_integration](../backend.hermes_integration/README.md), [backend.mcp_broker](../backend.mcp_broker/README.md), [backend.proofs_e_release](../backend.proofs_e_release/README.md).
- **Owner:** Neyvia / awareness.
- **Files:** [src/grant_agent/runtime_capability_inventory.py](../../src/grant_agent/runtime_capability_inventory.py).
