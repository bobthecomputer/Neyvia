# neyvia_prompt_dictation

Prompt-only text policy shared by HTTP, desktop and model dictation callers.

- **Public API:** `agreed_prefix`, `detect_language`, `frontier_text`, `prefix_words`, `process_prompt`, `revision_span`, `word_spans`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `dictation.prompt.commands`, `dictation.prompt.route`, `dictation.prompt.structure`.
- **Dependencies:** [backend.proofs_dictation](../backend.proofs_dictation/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_prompt_dictation.py](../../src/grant_agent/neyvia_prompt_dictation.py).
