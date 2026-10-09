# tool_manifest_registry

Validated inventory for external tools that extend Neyvia capabilities.

- **Public API:** `ToolManifest`, `ToolManifestRegistry`, `ToolOperationManifest`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a.tool-readiness`, `a.tool-reference`, `adapters.git.readiness`.
- **Dependencies:** [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.proofs_a_capabilities](../backend.proofs_a_capabilities/README.md), [backend.proofs_a_capability_tools](../backend.proofs_a_capability_tools/README.md), [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/tool_manifest_registry.py](../../src/grant_agent/tool_manifest_registry.py).
