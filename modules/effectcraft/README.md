# EffectCraft

Agent-usable EffectCraft (ArtCraft/storytold, an After Effects-style compositor in Rust) through its headless CLI: commands, comps and layers as a CL Scene, scripted edits, frames and renders.

- **Public API:** `commands`, `frame`, `info`, `render`, `run`, `scene_of`, `verify`, `neyvia.mod.effectcraft.commands`, `neyvia.mod.effectcraft.frame`, `neyvia.mod.effectcraft.info`, `neyvia.mod.effectcraft.render`, `neyvia.mod.effectcraft.run`, `neyvia.mod.effectcraft.verify`.
- **Manual:** [effectcraft.cl](../../manuals/cl/effectcraft.cl).
- **Contracts:** `run effectcraft.verify-greeting()`, `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_video](../backend.laya_video/README.md).
- **Owner:** Marketplace / Mods.
- **Files:** [apps/effectcraft/effectcraft_mod.py](../../apps/effectcraft/effectcraft_mod.py), [apps/effectcraft/host-contract.json](../../apps/effectcraft/host-contract.json), [apps/effectcraft/manual.cl](../../apps/effectcraft/manual.cl), [apps/effectcraft/neyvia.module.json](../../apps/effectcraft/neyvia.module.json).
