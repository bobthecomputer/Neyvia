# runtime_wrapper

Provides backend / runtime_wrapper in Neyvia.

- **Public API:** `RuntimeWrapperSpec`, `RuntimeWrapperState`, `build_runtime_wrapper_execution_receipt`, `build_runtime_wrapper_phase_event`, `build_runtime_wrapper_spec`, `build_runtime_wrapper_state`, `replay_runtime_wrapper`, `runtime_wrapper_payload`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d.runtime.wrapper.event`, `d.runtime.wrapper.receipt`, `d.runtime.wrapper.replay`, `d.runtime.wrapper.spec`, `d.runtime.wrapper.state`.
- **Dependencies:** [backend.models](../backend.models/README.md), [backend.proofs_d_runtime](../backend.proofs_d_runtime/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/runtime_wrapper.py](../../src/grant_agent/runtime_wrapper.py).
