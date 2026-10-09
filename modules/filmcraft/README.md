# FilmCraft

Agent-usable FilmCraft (ArtCraft/storytold, MIT or Apache-2.0; a Premiere-style editor in Rust) through its headless CLI: commands, the sequence as a CL Scene, scripted edits, export and frames.

- **Public API:** `commands`, `export`, `frame`, `inspect`, `run`, `scene_of`, `verify`, `neyvia.mod.filmcraft.commands`, `neyvia.mod.filmcraft.export`, `neyvia.mod.filmcraft.frame`, `neyvia.mod.filmcraft.inspect`, `neyvia.mod.filmcraft.run`, `neyvia.mod.filmcraft.verify`.
- **Manual:** [filmcraft.cl](../../manuals/cl/filmcraft.cl).
- **Contracts:** `run filmcraft.verify-greeting()`, `run modules.verify-map()`.
- **Outcome contracts:** No outcome binding yet.
- **Dependencies:** [backend.__init__](../backend.__init__/README.md), [backend.laya_video](../backend.laya_video/README.md).
- **Owner:** Marketplace / Mods.
- **Files:** [apps/filmcraft/filmcraft_mod.py](../../apps/filmcraft/filmcraft_mod.py), [apps/filmcraft/host-contract.json](../../apps/filmcraft/host-contract.json), [apps/filmcraft/manual.cl](../../apps/filmcraft/manual.cl), [apps/filmcraft/neyvia.module.json](../../apps/filmcraft/neyvia.module.json).
