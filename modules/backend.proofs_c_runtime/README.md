# proofs_c_runtime

Executable runtime contracts; checks use real state, not result schemas.

- **Public API:** `check_catalog`, `check_ingested`, `check_mcp_compact`, `check_mcp_described`, `check_mcp_receipt`, `check_mcp_search`, `check_memory_saved`, `check_memory_search`, `check_node_env`, `check_node_version`, `check_plan`, `check_service_started`, `check_service_status`, `check_service_stopped`, `check_toolchain_discovery`, `check_toolchain_integrity`, `require`, `self_check`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `runtime.install.catalog`, `runtime.install.cycles`, `runtime.install.plan`, `runtime.mcp.authorization`, `runtime.mcp.discovery`, `runtime.mcp.host`, `runtime.mcp.progressive`, `runtime.mcp.receipt`, `runtime.memory.durable`, `runtime.memory.ingest`, `runtime.memory.search`, `runtime.node.environment`, `runtime.node.versions`, `runtime.service.identity`, `runtime.service.installation`, `runtime.service.lifecycle`, `runtime.service.spec`, `runtime.toolchain.cache`, `runtime.toolchain.discovery`, `runtime.toolchain.integrity`.
- **Dependencies:** [backend.install_profiles](../backend.install_profiles/README.md), [backend.managed_local_service](../backend.managed_local_service/README.md), [backend.managed_node_runtime](../backend.managed_node_runtime/README.md), [backend.marketplace_toolchain](../backend.marketplace_toolchain/README.md), [backend.mcp_broker](../backend.mcp_broker/README.md), [backend.memory](../backend.memory/README.md), [backend.neyvia_mcp](../backend.neyvia_mcp/README.md), [backend.progressive_tools](../backend.progressive_tools/README.md), [backend.proof_credential_guard](../backend.proof_credential_guard/README.md), [backend.proof_ports](../backend.proof_ports/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_c_runtime.py](../../src/grant_agent/proofs_c_runtime.py).
