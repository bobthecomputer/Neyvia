# prompt_amplifier

Revision-bound rough-prompt preparation before a connected agent turn.

- **Public API:** `PromptAmplifier`, `call`, `handle_command`, `minimal_edits`, `render_cl`, `render_minimal`, `render_prompt`, `service_for`, `neyvia.prompt.amplify`, `neyvia.prompt.edit`, `neyvia.prompt.get`.
- **Manual:** [awareness.cl](../../manuals/cl/awareness.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.connected_sessions.broker](../backend.connected_sessions.broker/README.md), [backend.connected_sessions.registry](../backend.connected_sessions.registry/README.md), [backend.paul_manual](../backend.paul_manual/README.md), [backend.prompt_coverage](../backend.prompt_coverage/README.md), [backend.transition_memory](../backend.transition_memory/README.md).
- **Owner:** Neyvia / awareness.
- **Files:** [src/grant_agent/prompt_amplifier.py](../../src/grant_agent/prompt_amplifier.py).
