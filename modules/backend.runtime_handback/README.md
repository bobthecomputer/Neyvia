# runtime_handback

Bring what a runtime produced back into the session that opened it.

- **Public API:** `build_handback`, `describe_handback`, `handback_messages`, `summarize_returns`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.handback.identity`, `d.runtime.handback.transcript`.
- **Dependencies:** [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/runtime_handback.py](../../src/grant_agent/runtime_handback.py).
