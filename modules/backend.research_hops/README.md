# research_hops

Bounded public research, expressed as a CL-Passage variation of CL-State.

- **Public API:** `admit_facts`, `admit_snippets`, `anchored_queries`, `claim_grounding_gate`, `claim_grounding_prompt`, `encoded`, `encyclopedia_search`, `field_terms`, `hop_ids`, `index_phrase`, `model_text`, `obj`, `observed_span`, `ordered_hops`, `project_source`, `rank_snippets`, `run`, `search_phrase`, `select_evidence`, `snippet_choice_payload`, `source_cached`, `windows`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.autopilot_model](../backend.autopilot_model/README.md), [backend.cl.tokens](../backend.cl.tokens/README.md), [backend.cl.turn_context](../backend.cl.turn_context/README.md), [backend.laya_client.contracts](../backend.laya_client.contracts/README.md), [backend.laya_service](../backend.laya_service/README.md), [backend.research_pipeline](../backend.research_pipeline/README.md), [backend.research_sources](../backend.research_sources/README.md), [backend.transition_memory](../backend.transition_memory/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/research_hops.py](../../src/grant_agent/research_hops.py).
