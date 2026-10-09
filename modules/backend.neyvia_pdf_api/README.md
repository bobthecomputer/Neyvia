# neyvia_pdf_api

Authenticated, workspace-scoped PDF file transport (including PDF.js range reads).

- **Public API:** `rasterize`, `serve_file`, `serve_raster`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [pdf.cl](../../manuals/cl/pdf.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.pdf-render`, `p22.pdf.backend-range-raster-worker`.
- **Dependencies:** [backend.neyvia_pdf_tools](../backend.neyvia_pdf_tools/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / pdf.
- **Files:** [src/grant_agent/neyvia_pdf_api.py](../../src/grant_agent/neyvia_pdf_api.py).
