# Scene core API v1 (stable)

Owner: LAYAG, track/laya-glance. Plan 23. One core for UI, Blender, Godot, Unity,
Roblox and trading. No training runs, no new heads: define predicates, write
examples as episodes (plan 21).

```python
from grant_agent.scene_core import (Adapter, register, transcribe, vocabulary,
                                    judge, improve, episode, admit_approximate)
```

## 1. Register a domain adapter (the only per-domain code)

```python
register("blender", Adapter(
    transcribe=observe_source,        # source -> raw Scene dict (observations only)
    vocabulary=read_predicates,       # () -> [Predicate]  (load from your CL chapter)
    fixes={"mesh.recalculate": fix},  # (source, finding) -> receipt   (optional)
    checkpoint=capture,               # source -> snapshot             (required for fixes)
    restore=restore,                  # (source, snapshot) -> None, raise on failure
    episode_input=None))              # optional: scene -> (domain, input) for episodes
```

A domain id is `[a-z][a-z0-9-]{0,63}`; registering a second adapter for the same id
raises. Register in the process that hosts the native tools. Adapters live next to
their domain manual; there is no per-domain judge.

## 2. Scene

`transcribe(domain, source) -> Scene`

```
Scene = {schema:"neyvia.scene.v1", domain, surface, nodes:[Node], metrics?, provenance?,
         truncated?, modelTranscription?, measured?, viewport?,
         sha256, cl, transcriptionMs}                    # last three added by the core
Node  = {id:str (stable), kind:str, attributes:{}, measurements:{}, relations:{},
         certainty:"observed"|"uncertain"|"unreadable"}
```

* Adapters return actual observations; a fact that was not observed is absent or null.
* `measured:"approximate"` marks facts measured indirectly (pixels, vision, sampled
  renders). Such scenes are admitted through calibration (section 4), never because a
  predicate merely matched.
* `modelTranscription:true` marks facts a model asserted; never admitted by itself.
* At most 2000 nodes, unique ids. `sha256` binds the scene; `judge` refuses a scene
  whose content changed after transcription.

## 3. Vocabulary and predicates

`vocabulary(domain) -> [Predicate]`

```
Predicate = {id, condition, severity, evidence:[field-path], fix:{action, arguments},
             fuzzy?:bool, means?:str}
condition = {field:"measurements.nonManifoldEdges", op:"gt", value:0}
          | {all:[condition...]} | {any:[condition...]}
ops: eq lt le gt ge nonempty matches(regex, case-insensitive; (?-i:...) for case)
```

Three-valued: a missing fact is unknown (`None`); `all` is False if any part is False,
`any` is True if any part is True. Use a layer guard such as
`{field:"measurements.source", op:"eq", value:"pixels"}` inside `all` so one predicate
can carry branches for different observers without making the other branch unknown.
Predicate text is never executed.

## 4. Judge

`judge(scene, rules=None, *, root=None, user="", record=True, calibration=None, level=0.95)`

```
{findings:[{predicate, node, severity, evidence, fix}], admitted, confidence,
 confidenceKind, complete, unknown:[predicate], unknownNodes:{predicate:[node]},
 sceneSha256, vocabularySha256, escalation, ms}
```

* Exact scenes: an observed crisp defect admits a broken verdict; a clean verdict needs
  complete coverage (no unknown predicate, not truncated).
* Approximate scenes: `admit_approximate(findings, rules, calibration, level)`.
  `calibration = {predicate: {tp, fp, tn, fn, precisionLower, npvLower}}`, bounds are
  the conservative k/(n+1) rates from labelled episodes. Broken is admitted when a fired
  predicate's `precisionLower >= level`; clean only when every predicate's
  `npvLower >= level`. Otherwise `escalation = one model look` (one call, one
  screenshot, never a tour).
* Fuzzy predicates query plan 21's episode store; retrieval never invents a node finding.

## 5. Episodes (instant learning)

`episode(root, scene, label, reason, source, *, user="", layer="corrective", weight=1, split=None)`
appends immediately to `.neyvia/laya/instant.sqlite` (no training). `source` is
idempotent provenance; corrections reuse it; `forget(source)` removes it. Personal
labels need a user. Automatic outcomes write weight 0.25 and cannot self-certify.
Domains `scene:*` and `ui-glance` never enter head consolidation.

## 6. Improve

`improve(domain, source, budget, *, root)` with
`budget={max_steps, max_seconds, allowed_fixes:[...], guards:{metric:"min"|"max"}, nodes?:[id]}`:
transcribe -> judge -> apply one allowed fix -> transcribe again; keep only a strict
reduction of findings with no guarded metric regression, else restore (restore must
raise on failure). Every transition is a receipt in `.neyvia/laya/improve/`. Trading
is proposal-only (`status:"human-review-only"`).

* A predicate's `fix` may list `alternatives:[action]` (at most 8): the first of
  `[action, *alternatives]` that the caller allowed and the adapter registered is applied.
* `nodes` focuses the loop on those findings; all findings still count for keep/revert.
* A fix function may return a dict; it is stored as the step's `fix` receipt (what was edited).

## 7. Native tools and SDK

Native: `neyvia.scene.transcribe`, `neyvia.scene.vocabulary`, `neyvia.laya.judge`,
`neyvia.scene.improve`, `neyvia.scene.episode` (shared), and for UI
`neyvia.laya.glance`, `neyvia.laya.glance_learn`, `neyvia.laya.glance_lesson`,
`neyvia.laya.glance_contracts`, `neyvia.laya.glance_proof`. Mutations have verified
postconditions (`scene_core.OperationAdapter`).

SDK: `NeyviaClient(...).scenes` -> `SceneClient` with `transcribe(domain, source)`,
`vocabulary(domain)`, `judge(scene, predicates=?, domain=?, record=?)`,
`improve(domain, source, budget)`, `episode(scene, label, reason, source)`,
`glance(scene=?, screenshot=?)`, `lesson(scene, node, predicate, label, reason, source)`.
Results are normal Neyvia receipts.

### Out-of-repo adapters (SDK seam)

A domain that lives in another repository (trading) does not register inside Neyvia.
It transcribes its own raw scene and brings its own vocabulary in the same predicate
shape; the core validates both as data (`check_predicates`: operators `eq lt le gt ge
nonempty matches` only, dotted fact paths, numeric ordering, compiled regex <= 1000
chars, <= 500 predicates, depth <= 8) and never executes them.

```python
# in process (PYTHONPATH=<neyvia>/src)
from grant_agent.scene_core import normalize, judge
verdict = judge(normalize('trading', raw_scene), predicates, record=False)
# over HTTP with the standalone SDK (src/neyvia_sdk) or packages/neyvia-sdk judgeScene()
NeyviaClient('http://127.0.0.1:<port>').judge_scene(raw_scene, predicates=predicates, domain='trading')
```

`neyvia.laya.judge` accepts `{scene, domain?, predicates?, record?}`; a scene without a
`sha256` is bound with `normalize(domain, scene)` before judgment. Same findings shape,
same three-valued unknowns. Contract: `run laya-glance.prove-sdk-seam()`; evidence
`scripts/core_sdk_seam_proof.py` -> `scripts/evidence/CORE-sdk-seam.json`.

## 8. UI adapter (reference implementation)

`grant_agent.laya_glance` registers domain `ui`; vocabulary in
`manuals/cl/laya-glance.cl` (`-- @bug` lines): see-through, clipped-text, raw-error,
encoded-path, internal-id, blank-render, overlap, unreadable-contrast,
off-screen-control, each with a named fix.

* DOM source: the perception collector (`perception_scene.js`) gives exact facts.
* Screenshot source: `laya_glance_image.transcribe_image` (Windows OCR + numpy pixel
  facts), `measured:"approximate"`, admitted through `config/laya_glance_calibration.json`.
* Both: `glance(dom_scene, screenshot=png)` fuses pixel contrast, cross-checks that the
  DOM covers >= 85% of visible text lines (else not clean), and adds pixel findings
  that calibration trusts at 0.95; others are reported as `advisory`.
* Lessons: `learn_node` writes `scene:ui-node:<predicate>` episodes keyed by visible
  words (cosine >= 0.8 over hashed words), effective on the next glance; only for
  text-intrinsic predicates.
* Gate: `scripts/laya_glance_gate.py [--budget s] <request.json>` answers P22's request
  (`commit, sourceBindings, changedSurfaces, renderReceipt, build, assignedPorts,
  observerPorts, variants`) with one row per surface x variant; P22's contract_gate
  selects it automatically. Proof: `scripts/core_gate_seam_proof.py`.
* Fixes (`grant_agent.laya_ui_fix`): a *tree source* `{tree, state, variant, ports, runs}`
  is a web source tree plus one state (`home`, `files-main`, `files-side-floating`,
  `pdf`). Transcribe = production build (cached per `web/src` digest) + fresh private
  Obscura render (settled; DOM and pixels re-taken until they describe one layout) +
  DOM/pixel hybrid, node ids keyed by content. Registered fixes: `ui.css.align-start`,
  `ui.css.intrinsic-width`, `ui.css.shrink-text` (clipped-text), `ui.css.stacking-layer`,
  `ui.css.opaque-surface` (see-through): override rules appended to the stylesheet that
  already styles the element; and recorded patches from `config/laya_ui_fix_library.json`
  (LAYA selects and verifies them; it does not author them). Checkpoint/restore = snapshot
  of `web/src`, verified by digest. Contract: `manuals/cl/laya-ui-fix.cl`; proof
  `scripts/core_ui_fix_proof.py` (three P22 bugs at 9589de605: wrong candidate reverted,
  named fix kept, each).

## 9. Assigned ports and scratch roots (proof harnesses)

Proof scripts keep their historical owned ports and output folders when nothing is
passed. A caller with its own allocation (lead, verifier) assigns it explicitly through
`grant_agent.assigned_ports`:

```
python scripts/laya3d_contracts.py --port-block 49171-49179 --scratch-root D:/NeyviaRuns/X
NEYVIA_ASSIGNED_PORTS=49171-49179 NEYVIA_SCRATCH_ROOT=D:/NeyviaRuns/X python ...   # env form
```

* A block is one ascending range of at least two ports. It is refused when it overlaps
  a block registered to another track (`REGISTERED`: plan 27 section 0 and
  `plans/12-board.md`); a sub-block of the script's own track is fine. Pairs come from
  the block start: (first, first+1), (first+2, first+3), ...
* With a block, every gate accepts only ports inside it: the 3D `Harness`
  (`laya3d_harness.owned_pair`; default = first pair), UI-fix renders
  (`laya_ui_fix.render_ports`) and the glance gate (`laya_glance_gate.request_ports`;
  the request's `assignedPorts` must lie inside the block).
* With a scratch root, `scripts/evidence/*` and `manuals/cl/*` writes go to
  `<root>/<same relative path>` (`output`), large outputs to `<root>/<track folder>`
  (`under`), and small runtime state to ignored `.agent_control/scratch/<slug>` on the
  local disk (`state`). Reads of a redirected manual use the scratch copy when present
  (`readable`).
* Scripts: `laya3d_contracts`, `laya3d_kronos`, `laya3d_engines`, `core_ui_fix_proof`
  (scratch: fresh `git archive` of 9589de605 + node_modules junction),
  `core_gate_seam_proof` (glances on the block's second pair), `laya_glance_gate`, and
  `laya_anim` on track/laya-anim. Contract: `manuals/cl/assigned-ports.cl`; proof
  `scripts/assigned_ports_proof.py`.

## 9. Video adapters (plan 28, one stack since 7 Oct)

`grant_agent.laya_video` registers domain `video` lazily. Source `{project, quality}` renders
the project's cut EDL (`neyvia.video.cut.v1`) headless with HyperFrames and measures the file;
source `{video, project?, brief?, fast?}` judges an already rendered file with the same
observers (a project's cut or free-form EDL only supplies ids, shot windows and caption DOM).
Vocabulary: the `-- @predicate` lines of `manuals/cl/laya-video.cl`, each with a named EDL fix
(`laya_video.FIXES`); `laya_video.improve_cut` runs rounds of `scene_core.improve` with exact
rollback. `grant_agent.laya_video_edit` registers `video-edit` (the composition before
rendering; source `{project, brief?}`, vocabulary: the `video-edit` `-- @bug` lines of
`manuals/cl/video.cl`). Free-form editing behind `neyvia.video.*`: `video_hyperframes`.
Fast outcome contracts: `video_contracts`. The tools, free-form EDL, pre-render checks and
contracts came from track/laya-video; the judge and loop from track/video.

## Measured limits (see scripts/evidence/LAYAG-report.md)

Pixel recall is low for overlap, off-screen controls and see-through on phone peek
sheets; a pixel-only clean verdict is never admitted. A screenshot glance is ~0.5 s
(OCR ~0.2 s); predicate judgment is ~6 ms. UI fixes act only on a source tree (a
perception scene or screenshot stays proposal-only); one build + render is ~2 minutes on
this laptop, so an improve step costs minutes, not milliseconds. App state that loads
asynchronously (provider probes, sidebar sources) can still differ between renders and
can make a good fix look unkept; the guards are therefore font size and page errors, not
text-node counts. 3D engine adapters belong to LAYA3D on this API (lazy: `laya3d`,
`blender`, `godot`, `unity`, `roblox`).

## 9. Lenses: eyes that grow (plan 24, VISION)

`grant_agent.scene_core.lenses` keeps LAYA's eyes as a registry (`config/laya_lenses.json`;
`NEYVIA_LAYA_LENSES` points experiments at a run-local copy). A lens measures one observable
and emits Scene facts:

```
{id, inputType: screenshot|dom|render|mesh, emits:{fact:{type, cl}}, cost, provenance:{author, at, receipt},
 status: active|candidate|rejected|retired, decision:{reasons, checkAccuracy, receipt},
 program?, programSha256?, branch?:{predicate, condition}}
```

* Built-in lenses describe the existing observers (pixel transcriber, DOM collector, Blender facts).
* Program lenses are model-written `measure(rgb, nodes, viewport) -> {facts:{node:{fact:value}}, nodes:[...]}`,
  run only when the file hash equals `programSha256`, after an AST allow-list (numpy/scipy.ndimage/math...,
  no files, os, eval, dunders) with restricted builtins and import hook. Failing lenses leave facts unknown.
* `apply(scene, rgb, input_type=...)` merges active lens facts into a pixel scene (the UI adapter calls it
  after `transcribe_image`). `with_branches(rules, input_type)` ORs each active lens `branch` (bounded predicate
  data, never code) into its predicate; a predicate marked `awaitsLens` is defined by its branches alone.
* `identity(input_type)` is part of `laya_glance.transcriber_version()`: adopting a screenshot lens changes the
  calibration identity, so `scripts/vision_promote.py` rebuilds `config/laya_glance_calibration.json`.
  `load_calibration` falls back to the shipped snapshot when a local file is bound to an older identity.

The loop (`grant_agent.laya_vision`): `look()` executes the one model look (gpt-6-luna via `codex exec`,
`autopilot_model.decide`), answering verdict + per-type labels + a CL description in lens ids + missing
observables; `remember()` writes it as episodes (look memory + node lessons); `recall()` answers a
near-identical screenshot locally; `author_lens()` has Luna write a candidate lens, which
`scripts/vision_evolve.py` keeps only if CHECK-group accuracy improves within the glance budget and retires
by ablation. 3D renders: `grant_agent.laya_vision_render` (domain `render3d`, CL in `manuals/cl/laya-vision.cl`).
