# scroll_pack

Scroll Study's untrusted pack boundary; source spans use Unicode character offsets.

- **Public API:** `is_graded`, `read_scrollpack`, `validate_pack`, `write_scrollpack`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `p22.scroll.reviewed-export-singleuse-outcome`.
- **Dependencies:** [backend.scroll_study_format](../backend.scroll_study_format/README.md), [backend.subprocess_utils](../backend.subprocess_utils/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/scroll_pack.py](../../src/grant_agent/scroll_pack.py).
