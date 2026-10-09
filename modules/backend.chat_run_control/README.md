# chat_run_control

Cancellation and recovery for a single active chat, shared by desktop and web processes.

- **Public API:** `ChatRunCancelled`, `active_chat_run`, `chat_cancellation_requested`, `chat_run_status`, `compact_recorded_results`, `note_runtime_process`, `process_started_at`, `record_chat_run_result`, `request_chat_cancellation`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `control.result-compaction`, `control.result-retention`.
- **Dependencies:** [backend.chat_stream](../backend.chat_stream/README.md), [backend.harness_jobs](../backend.harness_jobs/README.md), [backend.proofs_a_control](../backend.proofs_a_control/README.md), [backend.turn_compartment](../backend.turn_compartment/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/chat_run_control.py](../../src/grant_agent/chat_run_control.py).
