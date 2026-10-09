# proofs_dictation

Executable dictation policy contracts shared by every production entry point.

- **Public API:** `after`, `before`, `check_prompt`, `provider_checks`, `self_check`, `validate_stream`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `dictation.names.persisted`, `dictation.names.scoped`, `dictation.prompt.commands`, `dictation.prompt.route`, `dictation.prompt.structure`, `dictation.provider.fallback`, `dictation.provider.finalise`, `dictation.provider.partials`, `dictation.stream.preallocation`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.neyvia_prompt_dictation](../backend.neyvia_prompt_dictation/README.md), [backend.proof_ports](../backend.proof_ports/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/proofs_dictation.py](../../src/grant_agent/proofs_dictation.py).
