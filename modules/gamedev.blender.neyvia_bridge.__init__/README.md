# __init__

Blender-native scene bridge; networking never calls bpy from its worker.

- **Public API:** `NEYVIA_OT_connect`, `NEYVIA_PT_bridge`, `register`, `unregister`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [gamedev.blender.neyvia_bridge.mesh_quality](../gamedev.blender.neyvia_bridge.mesh_quality/README.md), [gamedev.blender.neyvia_bridge.shape_program](../gamedev.blender.neyvia_bridge.shape_program/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [scripts/gamedev/blender/neyvia_bridge/__init__.py](../../scripts/gamedev/blender/neyvia_bridge/__init__.py).
