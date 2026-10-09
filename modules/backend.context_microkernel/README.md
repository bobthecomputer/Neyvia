# context_microkernel

Phase 0/1 Context Microkernel glue: metrics, unified bundles, cache-control.

- **Public API:** `ContextTurnMetrics`, `ModelVisibleContext`, `assemble_prompt_with_cache`, `emit_prompt_cache_control`, `provider_wire_cache_fields`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.context-cache`, `control.context-cache-wire`, `control.context-metrics`.
- **Dependencies:** [backend.context_engine](../backend.context_engine/README.md), [backend.context_manager](../backend.context_manager/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/context_microkernel.py](../../src/grant_agent/context_microkernel.py).
