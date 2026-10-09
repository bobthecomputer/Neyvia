# neyvia_outputs

Published outputs share the workspace bus, durable identity and guarded previews.

- **Public API:** `call`, `failure`, `get`, `handle_command`, `listing`, `publish`, `neyvia.artifact.get`, `neyvia.artifact.list`, `neyvia.artifact.open`, `neyvia.artifact.publish`.
- **Manual:** [local-app-open.cl](../../manuals/cl/local-app-open.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [outputs.cl](../../manuals/cl/outputs.cl), [workspace.cl](../../manuals/cl/workspace.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `outputs.backend-publication-byte-recovery`, `p22.image-studio.pixel-edit-journey`, `p22.workspace.output-journey`.
- **Dependencies:** [backend.cl.renderer_effects](../backend.cl.renderer_effects/README.md), [backend.neyvia_files_tools](../backend.neyvia_files_tools/README.md), [backend.neyvia_panes](../backend.neyvia_panes/README.md), [backend.neyvia_voice](../backend.neyvia_voice/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / local-app-open.
- **Files:** [src/grant_agent/neyvia_outputs.py](../../src/grant_agent/neyvia_outputs.py).
