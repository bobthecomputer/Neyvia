# HyperFrames

Agent-usable HyperFrames (HeyGen, Apache-2.0): lint, observe the timeline, render headless to MP4 with outcome contracts, snapshot frames and run the Studio privately.

- **Public API:** `edit`, `lint`, `outcome`, `render`, `snapshot`, `studio`, `timeline`, `verify`, `neyvia.mod.hyperframes.edit`, `neyvia.mod.hyperframes.lint`, `neyvia.mod.hyperframes.render`, `neyvia.mod.hyperframes.snapshot`, `neyvia.mod.hyperframes.studio`, `neyvia.mod.hyperframes.timeline`, `neyvia.mod.hyperframes.verify`.
- **Manual:** [hyperframes.cl](../../manuals/cl/hyperframes.cl).
- **Contracts:** `run hyperframes.verify-greeting()`, `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_video](../backend.laya_video/README.md).
- **Owner:** Marketplace / Mods.
- **Files:** [apps/hyperframes/host-contract.json](../../apps/hyperframes/host-contract.json), [apps/hyperframes/hyperframes_mod.py](../../apps/hyperframes/hyperframes_mod.py), [apps/hyperframes/manual.cl](../../apps/hyperframes/manual.cl), [apps/hyperframes/neyvia.module.json](../../apps/hyperframes/neyvia.module.json).
