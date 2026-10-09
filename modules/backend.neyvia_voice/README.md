# neyvia_voice

Final voice transcripts use the existing workspace bus; never launch a run.

- **Public API:** `Refusal`, `append_audit`, `call`, `catalog`, `choose`, `clean`, `command`, `execute`, `forward_command`, `handle_command`, `normalized`, `parse`, `resolve`, `sessions`, `neyvia.app.open`, `neyvia.voice.command`, `neyvia.voice.commands`.
- **Manual:** [local-app-open.cl](../../manuals/cl/local-app-open.cl), [local-rendering.cl](../../manuals/cl/local-rendering.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [outputs.cl](../../manuals/cl/outputs.cl), [voice.cl](../../manuals/cl/voice.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.cl.renderer_effects](../backend.cl.renderer_effects/README.md), [backend.connected_sessions.forward](../backend.connected_sessions.forward/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / local-app-open.
- **Files:** [src/grant_agent/neyvia_voice.py](../../src/grant_agent/neyvia_voice.py).
