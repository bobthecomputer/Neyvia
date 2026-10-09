# neyvia_dictation_providers

Dictation providers: where the speech is turned into words while Paul talks.

- **Public API:** `CloudStream`, `CodexRpc`, `CodexStream`, `OpenAIStream`, `ProviderError`, `Transcript`, `choose`, `codex_binary`, `codex_probe`, `describe`, `note_failure`, `note_success`, `open_stream`, `openai_key`, `recent_failure`, `resample_16k_to_24k`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `dictation.provider.fallback`, `dictation.provider.finalise`, `dictation.provider.partials`.
- **Dependencies:** [backend.local_network_policy](../backend.local_network_policy/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_dictation_providers.py](../../src/grant_agent/neyvia_dictation_providers.py).
