# laya_instant

Local append-only episodic learning. Frozen encoders; no optimizer on writes.

- **Public API:** `Episodes`, `canonical`, `encode`, `encoder`, `input_key`, `latest_episodes`, `query`, `routing_encoder`, `store`, `unique_vectors`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.laya_curriculum](../backend.laya_curriculum/README.md), [backend.laya_host](../backend.laya_host/README.md), [backend.laya_instant_calibration](../backend.laya_instant_calibration/README.md), [backend.laya_instant_consolidate](../backend.laya_instant_consolidate/README.md), [backend.laya_instant_semantic](../backend.laya_instant_semantic/README.md), [backend.taste_vision](../backend.taste_vision/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/laya_instant.py](../../src/grant_agent/laya_instant.py).
