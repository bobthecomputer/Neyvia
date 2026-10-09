# common

Core model architecture, token sequence construction, and confidence estimation for laya.

- **Public API:** `DecisionModel`, `amp_dtype`, `build_model`, `build_sequence`, `collate_items`, `confidence_from_probs`, `ece_score`, `proper_reward`, `render_criterion`, `render_options`, `serialize_state`, `td_lambda_targets`, `temp_bucket`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** None statically declared.
- **Owner:** Neyvia / neyvia.
- **Files:** [tools/laya/laya/common.py](../../tools/laya/laya/common.py).
