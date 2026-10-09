# openai_adapter

Provides backend / openai_adapter in Neyvia.

- **Public API:** `CodeExecutionConfig`, `OpenAIRequestPlan`, `apply_attached_cache_control`, `apply_cache_control_to_payload`, `build_compaction_request`, `build_responses_request`, `build_responses_request_from_tool_compiler`, `resolve_compiled_tool_call`, `tools_from_skills`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.context-cache-wire`, `d.runtime.openai.request`, `d.runtime.openai.tools`, `proofs-c.models.provider-request`.
- **Dependencies:** [backend.context_microkernel](../backend.context_microkernel/README.md), [backend.model_tool_intelligence](../backend.model_tool_intelligence/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_c_models](../backend.proofs_c_models/README.md), [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md), [backend.skills](../backend.skills/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/openai_adapter.py](../../src/grant_agent/openai_adapter.py).
