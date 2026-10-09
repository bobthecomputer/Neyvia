# efficient_workflow

Four explicit, bounded lanes over the existing durable orchestration graph.

- **Public API:** `build_efficient_workflow`, `compact_dependency_context`, `continuation_checkpoint`, `continuation_instructions`, `is_user_instruction_turn`, `verification_result`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `proofs-b.engine.handoff`, `proofs-b.engine.verdict`, `proofs-b.engine.workflow`, `proofs-e-wz.workflow-budget`.
- **Dependencies:** [backend.agent_prompt_library](../backend.agent_prompt_library/README.md), [backend.capability_routes](../backend.capability_routes/README.md), [backend.neyvia_runtime_invocation](../backend.neyvia_runtime_invocation/README.md), [backend.proofs_b_engine](../backend.proofs_b_engine/README.md), [backend.proofs_e_wz](../backend.proofs_e_wz/README.md), [backend.reasoning_capabilities](../backend.reasoning_capabilities/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/efficient_workflow.py](../../src/grant_agent/efficient_workflow.py).
