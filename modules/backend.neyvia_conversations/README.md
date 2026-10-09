# neyvia_conversations

Provides backend / neyvia_conversations in Neyvia.

- **Public API:** `NeyviaConversationStore`, `build_lead_workers_preset`, `generated_title`, `typed_plan_hash`, `utc_now_iso`, `validate_typed_lead_plan`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `neyvia-core.conversation-activity`, `neyvia-core.conversation-deletion`, `neyvia-core.conversation-import`, `neyvia-core.conversation-pages`, `neyvia-core.conversation-question`, `neyvia-core.conversation-receipts`, `neyvia-core.conversation-turns`, `p22.chat-storage-compaction-outcome`, `proofs-b.engine.workflow`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.agent_delta](../backend.agent_delta/README.md), [backend.efficient_workflow](../backend.efficient_workflow/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_d_neyvia](../backend.proofs_d_neyvia/README.md), [backend.semantic_missions](../backend.semantic_missions/README.md), [backend.verified_operations](../backend.verified_operations/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_conversations.py](../../src/grant_agent/neyvia_conversations.py).
