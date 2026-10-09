# neyvia_pdf_tools

The PDF bot side sends A2's typed actions and observes the same app state.

- **Public API:** `call_pdf`, `report_pdf_state`, `safe_pdf`, `tool_specs`, `neyvia.state`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [neyvia-core.cl](../../manuals/cl/neyvia-core.cl), [pdf.cl](../../manuals/cl/pdf.cl), [ui-planning.cl](../../manuals/cl/ui-planning.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.pdf-render`, `p22.pdf.backend-range-raster-worker`.
- **Dependencies:** [backend.neyvia_ui_client](../backend.neyvia_ui_client/README.md), [backend.neyvia_workspace_tools](../backend.neyvia_workspace_tools/README.md), [backend.pdf_document](../backend.pdf_document/README.md), [backend.ui_command_bus](../backend.ui_command_bus/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/neyvia_pdf_tools.py](../../src/grant_agent/neyvia_pdf_tools.py).
