# FilmCraft source mod

Optional Neyvia mod that drives [storytold/filmcraft](https://github.com/storytold/filmcraft)
headlessly. FilmCraft is a clean-room, pure-Rust reimplementation of the Adobe Premiere Pro
workflow by the ArtCraft team (storytold), dual-licensed MIT OR Apache-2.0; Neyvia uses it under
Apache-2.0. All credit for the editor, codecs and renderer goes to its authors. This folder only
contains Neyvia's thin wrapper, manual and contract; no FilmCraft code is vendored.

- Two builds exist from the two video tracks: track/laya-video built upstream `771b614` (filmcraft-cli 0.2.1,
  Rust 1.95, `D:\NeyviaRuns\video\build\filmcraft-target`); track/video built the clone in
  `D:\NeyviaRuns\video\upstream\filmcraft` into `D:\NeyviaRuns\video\track-video\target\filmcraft`.
  The mod's binary resolution is in `filmcraft_mod.py`.
- Toolchains and target directories stay on D: (C: is nearly full).

## Actions

`neyvia.mod.filmcraft.*`: `commands` (engine command list), `inspect` (the sequence as a CL Scene),
`run` (scripted engine commands), `export`, `frame` and `verify`. Each wraps a real `filmcraft-cli`
subcommand, runs with `CREATE_NO_WINDOW` and keeps paths inside the workspace or `D:\NeyviaRuns`.
`verify` builds an edit from two real captures (title, marker, scale keyframes) and checks the
decoded export frame by frame (300/300 frames, 0 black); the store proof
(`scripts/video_store_proof.py`) runs it with the mod switched on.

The typed per-command wrapper written on track/laya-video (`status`, `new_project`, `import_media`,
`place_clip`, `split`, `add_transition`, `add_title`, `apply_effect`, `animate`, `render_frame`) stays
in that branch's history (b9bf859c6); its commands are all reachable here through `run`.
