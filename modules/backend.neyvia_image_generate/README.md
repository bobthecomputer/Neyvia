# neyvia_image_generate

Image generation through the Codex CLI's own built-in image tool.

- **Public API:** `codex_cli_status`, `generate_image`, `list_jobs`, `sweep_stale_jobs`.
- **Manual:** [image-studio.cl](../../manuals/cl/image-studio.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `image.generate.deadline`, `image.generate.job-settled`, `image.generate.preflight`.
- **Dependencies:** [backend.subprocess_utils](../backend.subprocess_utils/README.md), [backend.web_backend](../backend.web_backend/README.md).
- **Owner:** Neyvia / image-studio.
- **Files:** [src/grant_agent/neyvia_image_generate.py](../../src/grant_agent/neyvia_image_generate.py).
