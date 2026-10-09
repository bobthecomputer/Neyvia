# laya_glance

UI adapter for the shared Scene core.

- **Public API:** `calibration_from_counts`, `conformal_lower`, `cross_check`, `fuse_pixels`, `glance`, `learn`, `learn_node`, `load_calibration`, `locate_quote`, `node_domain`, `node_key`, `node_text`, `pixel_version`, `quotes`, `transcribe`, `transcriber_version`, `ui_adapter`, `update_calibration`.
- **Manual:** [laya-glance.cl](../../manuals/cl/laya-glance.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `layag.pixel-before-after`, `layag.scene-predicates`.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_glance_image](../backend.laya_glance_image/README.md), [backend.laya_instant](../backend.laya_instant/README.md), [backend.laya_ui_fix](../backend.laya_ui_fix/README.md), [backend.scene_core.__init__](../backend.scene_core.__init__/README.md), [backend.scene_core.lenses](../backend.scene_core.lenses/README.md).
- **Owner:** Neyvia / laya-glance.
- **Files:** [src/grant_agent/laya_glance.py](../../src/grant_agent/laya_glance.py).
