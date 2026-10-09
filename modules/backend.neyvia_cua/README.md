# neyvia_cua

PC-owned MIT Cua Driver sessions, background preview, receipts and takeover.

- **Public API:** `CuaService`, `app_name`, `bind_chat`, `call`, `canonical_client`, `forward_desktop`, `handle_command`, `native_request`, `now`, `refusal`, `result`, `serve_http`, `service_for`, `stream`, `neyvia.cua.action`, `neyvia.cua.adapt`, `neyvia.cua.capture`, `neyvia.cua.flow`, `neyvia.cua.inspect`, `neyvia.cua.log`, `neyvia.cua.state`, `neyvia.cua.verify`, `neyvia.cua.wait`, `neyvia.cua.windows`.
- **Manual:** [computer-use.cl](../../manuals/cl/computer-use.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cua_adaptation](../backend.cua_adaptation/README.md), [backend.cua_native](../backend.cua_native/README.md), [backend.cua_upstream](../backend.cua_upstream/README.md), [backend.durability](../backend.durability/README.md), [backend.neyvia_agentview](../backend.neyvia_agentview/README.md), [backend.neyvia_cua_mcp](../backend.neyvia_cua_mcp/README.md), [backend.neyvia_remote](../backend.neyvia_remote/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / computer-use.
- **Files:** [src/grant_agent/neyvia_cua.py](../../src/grant_agent/neyvia_cua.py).
