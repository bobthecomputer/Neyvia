# evolver_domains

Real, bounded GPT-6 Luna evaluators for the first Evolver text domains.

- **Public API:** `DomainEvaluator`, `Luna`, `ModelFailure`, `digest`, `domain_spec`, `notes_judge`, `propose`, `skill_judge`, `token_count`.
- **Manual:** [hill-climb.cl](../../manuals/cl/hill-climb.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cl_skill](../backend.cl_skill/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md), [backend.neyvia_notes_tools](../backend.neyvia_notes_tools/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / hill-climb.
- **Files:** [src/grant_agent/evolver_domains.py](../../src/grant_agent/evolver_domains.py).
