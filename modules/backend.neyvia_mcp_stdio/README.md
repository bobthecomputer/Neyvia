# neyvia_mcp_stdio

Compact stdio MCP transport for model-facing N-E-Y-V-I-A tools.

- **Public API:** `CompactNeyviaMCPServer`, `main`, `serve`.
- **Manual:** [memory.cl](../../manuals/cl/memory.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `memory.launcher-host-binding`, `native.mcp.discovery`, `native.mcp.read-only`, `proofs-b.engine.mcp-authority`.
- **Dependencies:** [backend.agent_questions](../backend.agent_questions/README.md), [backend.cl.protocol](../backend.cl.protocol/README.md), [backend.crashproof](../backend.crashproof/README.md), [backend.local_provisioning](../backend.local_provisioning/README.md), [backend.manual_first](../backend.manual_first/README.md), [backend.native_access](../backend.native_access/README.md), [backend.neyvia_conversations](../backend.neyvia_conversations/README.md), [backend.neyvia_gateway](../backend.neyvia_gateway/README.md), [backend.neyvia_mcp](../backend.neyvia_mcp/README.md), [backend.neyvia_memory_tools](../backend.neyvia_memory_tools/README.md), [backend.situation_interface](../backend.situation_interface/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.workspace_intelligence](../backend.workspace_intelligence/README.md).
- **Owner:** Neyvia / memory.
- **Files:** [src/grant_agent/neyvia_mcp_stdio.py](../../src/grant_agent/neyvia_mcp_stdio.py).
