# laya_calibrate

Build the labelled corpora, admit the training cases into a fresh LAYA service, measure held-out accuracy.

- **Public API:** `admit`, `benchmark_tasks`, `build_page_done`, `build_route`, `build_taste`, `build_vocab`, `calibrate`, `evaluate`, `layer_id`, `manual_texts`, `page_texts`, `phrase`, `post`, `raw_decide`, `read_jsonl`, `start_service`, `wilson_low`, `write_jsonl`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_host](../backend.laya_host/README.md), [backend.neyvia_manuals](../backend.neyvia_manuals/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/laya_calibrate.py](../../scripts/laya_calibrate.py).
