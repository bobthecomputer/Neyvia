# subprocess_utils

Provides backend / subprocess_utils in Neyvia.

- **Public API:** `background_creationflags`, `capture_bounded_process`, `hidden_windows_subprocess_kwargs`, `install_hidden_subprocess_default`, `process_is_alive`, `split_process_command`, `stable_working_path`, `windows_pid_alive`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `native.runtime.process-journey`, `proofs-e-wz.hidden-default`, `proofs-e-wz.hidden-options`, `proofs.scratch-isolation`, `sessions.workspace.cli`.
- **Dependencies:** [backend.proofs_e_wz](../backend.proofs_e_wz/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/subprocess_utils.py](../../src/grant_agent/subprocess_utils.py).
