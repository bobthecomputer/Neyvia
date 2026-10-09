# capability_adapters

Demand-start adapter registry for capability execution.

- **Public API:** `AdapterExecution`, `CapabilityAdapterRegistry`, `CapabilityAdapterSessionStore`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `a.adapter-execution`, `a.adapter-file-inspection`, `a.adapter-session`, `a.android-approval`, `a.pdf-bounded`, `a.tool-workspace`, `adapters.ocr.boundaries`, `p22.capability-config.adapter-refusal`.
- **Dependencies:** [backend.capability_contracts](../backend.capability_contracts/README.md), [backend.encrypted_chat](../backend.encrypted_chat/README.md), [backend.folder_sync](../backend.folder_sync/README.md), [backend.git_reference_adapter](../backend.git_reference_adapter/README.md), [backend.managed_local_service](../backend.managed_local_service/README.md), [backend.mesh_service](../backend.mesh_service/README.md), [backend.module_marketplace](../backend.module_marketplace/README.md), [backend.nearby_send](../backend.nearby_send/README.md), [backend.p2p_cache](../backend.p2p_cache/README.md), [backend.p2p_provider](../backend.p2p_provider/README.md), [backend.proofs_a_capabilities](../backend.proofs_a_capabilities/README.md), [backend.proofs_a_capability_tools](../backend.proofs_a_capability_tools/README.md), [backend.proofs_b_adapters](../backend.proofs_b_adapters/README.md), [backend.secret_broker](../backend.secret_broker/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/capability_adapters.py](../../src/grant_agent/capability_adapters.py).
