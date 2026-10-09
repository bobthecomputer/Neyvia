# __init__

Shared transcribe -> define -> judge -> improve mechanism (Scene v1).

- **Public API:** `Adapter`, `OperationAdapter`, `SceneClient`, `adapter`, `admit_approximate`, `canonical`, `check_condition`, `check_predicates`, `episode`, `episode_input`, `evaluate`, `improve`, `judge`, `normalize`, `register`, `transcribe`, `value_at`, `vocabulary`.
- **Manual:** [laya-glance.cl](../../manuals/cl/laya-glance.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `core.sdk-seam`, `layag.scene-predicates`, `video.outcome-contracts`.
- **Dependencies:** [backend.laya_glance](../backend.laya_glance/README.md), [backend.laya_instant](../backend.laya_instant/README.md), [backend.laya_video](../backend.laya_video/README.md), [backend.laya_video_edit](../backend.laya_video_edit/README.md), [backend.scene_core.gamedev](../backend.scene_core.gamedev/README.md), [backend.scene_core.image_model](../backend.scene_core.image_model/README.md).
- **Owner:** Neyvia / laya-glance.
- **Files:** [src/grant_agent/scene_core/__init__.py](../../src/grant_agent/scene_core/__init__.py).
