# ocr_benchmark

Deterministic OCR evaluation and routing primitives.

- **Public API:** `OcrPageSignals`, `aggregate_scores`, `character_error_rate`, `evaluate_benchmark_manifest`, `load_candidate_registry`, `normalize_ocr_text`, `score_ocr_sample`, `select_ocr_route`, `validate_benchmark_manifest`, `word_error_rate`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `d-ui.ocr-candidates`, `d-ui.ocr-quality`, `d-ui.ocr-route`.
- **Dependencies:** [backend.proofs_d_ui_planning](../backend.proofs_d_ui_planning/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/ocr_benchmark.py](../../src/grant_agent/ocr_benchmark.py).
