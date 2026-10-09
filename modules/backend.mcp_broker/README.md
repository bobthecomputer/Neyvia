# mcp_broker

Outbound MCP broker MVP: discover → describe → call with auth + approval receipts.

- **Public API:** `BrokerReceipt`, `McpOutboundBroker`, `McpServerState`, `McpTransport`, `SseTransportStub`, `StdioJsonRpcTransport`, `StubTransport`, `default_demo_config`, `load_broker_config`, `mcp_tool_specs`, `register_with_progressive_surface`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `runtime.mcp.authorization`, `runtime.mcp.discovery`, `runtime.mcp.host`, `runtime.mcp.progressive`, `runtime.mcp.receipt`.
- **Dependencies:** [backend.mcp_http_transport](../backend.mcp_http_transport/README.md), [backend.mcp_protocol](../backend.mcp_protocol/README.md), [backend.model_tool_intelligence](../backend.model_tool_intelligence/README.md), [backend.progressive_tools](../backend.progressive_tools/README.md), [backend.proofs_c_runtime](../backend.proofs_c_runtime/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/mcp_broker.py](../../src/grant_agent/mcp_broker.py).
