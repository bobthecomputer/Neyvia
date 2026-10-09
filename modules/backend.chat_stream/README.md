# chat_stream

Bounded, authenticated chat event polling shared by web and desktop bridges.

- **Public API:** `StreamCoalescer`, `append_chat_stream`, `begin_chat_stream`, `last_stream_event`, `read_chat_stream`, `safe_tool_display`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.stream-frame`, `control.stream-order`, `control.stream-tail`, `proofs-e.chat.desktop-stream`, `proofs-e.chat.safe-display`.
- **Dependencies:** [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.proofs_e_chat](../backend.proofs_e_chat/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/chat_stream.py](../../src/grant_agent/chat_stream.py).
