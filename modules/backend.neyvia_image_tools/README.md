# neyvia_image_tools

Image Studio state and real pixel edits; generation reuses the existing provider.

- **Public API:** `call`, `generation_worker`, `inside`, `inspect`, `publish`, `report_state`, `serve_file`, `neyvia.image.composite`, `neyvia.image.crop`, `neyvia.image.export`, `neyvia.image.generate`, `neyvia.image.open`, `neyvia.image.resize`, `neyvia.image.state`.
- **Manual:** [image-studio.cl](../../manuals/cl/image-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.image-studio.pixel-edit-journey`.
- **Dependencies:** [backend.neyvia_image_approval](../backend.neyvia_image_approval/README.md), [backend.neyvia_outputs](../backend.neyvia_outputs/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md), [backend.visual_specifications](../backend.visual_specifications/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / image-studio.
- **Files:** [src/grant_agent/neyvia_image_tools.py](../../src/grant_agent/neyvia_image_tools.py).
