# neyvia_dictation

Dictation: speech to prompt text with the local Phonon-2 engine, shared with the dictation service.

- **Public API:** `DictationError`, `call`, `handle_command`, `language_history`, `names`, `process`, `read_settings`, `redecode`, `respond_command`, `serve_http`, `status`, `stop`, `stream`, `transcribe_file`, `transcribe_pcm`, `write_settings`, `neyvia.dictation.names`, `neyvia.dictation.process`, `neyvia.dictation.status`, `neyvia.dictation.transcribe`.
- **Manual:** [dictation.cl](../../manuals/cl/dictation.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `dictation.names.persisted`, `dictation.names.scoped`, `dictation.prompt.structure`, `dictation.provider.fallback`, `dictation.provider.finalise`, `dictation.provider.partials`, `dictation.stream.preallocation`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.neyvia_prompt_dictation](../backend.neyvia_prompt_dictation/README.md), [backend.proofs_dictation](../backend.proofs_dictation/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / dictation.
- **Files:** [src/grant_agent/neyvia_dictation.py](../../src/grant_agent/neyvia_dictation.py).
