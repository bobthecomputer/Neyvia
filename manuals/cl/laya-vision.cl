CL 1
L laya-vision v1 -- Evolving vision (plan 24): lenses as a registry, the one model look executed, Luna-written lenses kept only on held-out groups, self-made practice; no training
A scene_core.lenses.entries() -> list -- Python API; config/laya_lenses.json: id, input type, emitted facts (output schema), cost, provenance, status, decision receipt; program lenses pinned by sha256
A laya_vision.look(screenshot:str, scene:object, verdict:object) -> look -- Python API (not yet a native tool); one gpt-6-luna call via codex exec: verdict, per-type labels, CL description of what it saw in lens ids, missing observables
A laya_vision.author_lens(observable:object, examples:list, images:list) -> lens -- Python API; one Luna call writes a candidate lens program for a missing observable; AST allow-list, pinned, restricted imports
P stream(run): run scripts/vision_stream.py --run D:/NeyviaRuns/VISION/stream-1 --practice D:/NeyviaRuns/VISION/practice/practice.json -- 495 labelled screenshots arrive; lenses, look memory, or one look; lenses written and decided per window
P practice(): run scripts/vision_practice.py --out D:/NeyviaRuns/VISION/practice -- inject known defects into real Neyvia pages in headless Obscura (ports 49131/49132); revert verified per shot
P render-practice(): run blender.exe -b --factory-startup --python scripts/vision_blender_practice.py -- D:/NeyviaRuns/VISION/render-practice -- flipped normals, floaters, wrong scale on Kronos models and props
P render-run(run): run scripts/vision_render_run.py --run D:/NeyviaRuns/VISION/render-1 -- the same loop on 3D renders, held out by subject
P proof(): run scripts/vision_proof.py -- recompute curves, recall, lens receipts and grouping; evaluate the checks below
C vision.verify cap: proof.maxLooksPerRun <= 200 -- block at most 200 model looks per run, each logged with tokens
C vision.verify ui-look-episodes: proof.uiLookEpisodesMissing == 0 -- block every UI model look is written as an episode at once
C vision.verify render-look-episodes: proof.renderLookEpisodesMissing == 0 -- block every render model look is written as an episode at once
C vision.verify ui-look-rate: proof.uiLookRateFalls == true -- block the model-look rate falls over the UI stream
C vision.verify ui-looks-avoided: proof.uiLooksAvoidedVsFrozen > 0 -- block fewer looks than frozen eyes would have needed on the same arrival order
C vision.verify render-look-rate: proof.renderLookRateFalls == true -- block the model-look rate falls over the 3D render run
C vision.verify decisions: proof.lensDecisions >= 2 -- block missing observables named by looks became Luna-written candidate lenses with a keep/reject receipt
C vision.verify kept: proof.keptLenses >= 1 -- block at least one candidate lens improved held-out check-group accuracy within the glance budget
C vision.verify pinned: proof.programLensesUnpinned == 0 -- block every program lens runs only at its registry sha256
C vision.verify sandbox: proof.programLensesInvalid == 0 -- block every program lens passes the AST allow-list
C vision.verify receipts: proof.programLensesWithoutReceipt == 0 -- block every program lens has its decision receipt
C vision.verify provenance: proof.programLensesWithoutProvenance == 0 -- block every program lens records who wrote it and when
C vision.verify grouped: proof.groupOverlap == 0 -- block fit, check and final surface groups never share an app surface
C vision.verify no-regression: proof.finalRecallDrops == 0 -- block adopted lenses never lower a type's recall on the final held-out groups
C vision.verify precision-kept: proof.finalPrecisionDrops == 0 -- block adopted lenses never lower a type's precision on the final held-out groups by more than 0.02
C vision.verify practice: proof.practiceEpisodes >= 100 -- block self-made UI practice gives perfectly labelled episodes
C vision.verify revert: proof.practiceRevertFailures == 0 -- block every injected defect was removed before the next shot
C vision.verify renders: proof.renderPracticeRenders >= 100 -- block self-made 3D renders with known faults exist
C vision.verify training: proof.training == false -- block no weights are fitted; lenses are programs, episodes are writes
C vision.verify cost: proof.paidCalls == 0 -- block model looks use the existing subscription route only
C vision.verify ocr2-decision: proof.secondPassDefaultMatchesDecision == true -- block the OCR second pass default is the one the pre-registered rule chose on the new held-out split
C vision.verify ocr2-new-split: proof.newSplitImages >= 150 -- block the second-pass decision was measured on at least 150 never-labelled captures, labelled blind
C vision.verify ocr2-precision: proof.newSplitPrecisionDrops == 0 -- block the second pass lowers no type's precision on the new held-out split by more than 0.05
C vision.verify ocr2-ids: proof.newSplitInternalIdPrecision >= 0.9 -- block recovered words never make internal-id fire on ordinary copy (was .20 before VISION2)
C vision.verify ocr2-identity: proof.textRunsDiffer == 0 -- block the faster text-run finder returns exactly the reference runs on every labelled capture
J truth labels|paul: "Ground truth is vision-sub-agent labels against Paul's review (LAYAG); a lens kept on them inherits their errors."
F A model look is untrusted data: it labels and names observables; it never executes and never sets calibration counts.
F Look memory answers only near-identical screenshots (CLIP cosine radius calibrated on dev labels to >= 0.95 per-type agreement).
F The OCR second pass is on by default (VISION2 decision, scripts/evidence/VISION2-ocr-decision.json); NEYVIA_LAYA_OCR_SECOND_PASS=0 opts out and changes the transcriber identity.
F Kept lenses change the transcriber identity; shipped calibration is rebuilt from the same labelled captures when a lens is promoted.
F Practice labels are region level (injected region positive, same region before injection negative); base pages may carry real defects elsewhere.
M lenses "A lens measures one observable and emits Scene facts; a program lens may OR one bounded predicate branch (data) into one predicate. Predicates without eyes (awaitsLens) are defined by their lens branches alone." src:"plan 24" state:verified

-- @render-predicate {"id":"flipped-normals","awaitsLens":true,"condition":{"field":"measurements.backfaceHoles","op":"gt","value":0},"means":"Faces of the subject point inward; with back-face culling they vanish and the surface shows holes or see-through patches.","fix":"Recalculate normals outside (mesh.recalculate) and re-render."}
-- @render-predicate {"id":"floaters","awaitsLens":true,"condition":{"field":"measurements.detachedParts","op":"gt","value":0},"means":"Small detached pieces float apart from the subject's body.","fix":"Delete loose parts below the size threshold (mesh.remove_floaters)."}
-- @render-predicate {"id":"wrong-scale","condition":{"all":[{"field":"kind","op":"eq","value":"object"},{"any":[{"field":"measurements.coverage","op":"gt","value":0.5},{"field":"measurements.coverage","op":"lt","value":0.0004}]}]},"means":"The subject is far larger or smaller than its declared real-world height (judged against the 1.8 m reference).","fix":"Apply the unit scale so the subject matches its declared height (engine.scale)."}
