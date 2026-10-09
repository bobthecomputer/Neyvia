CL 1
L laya-3d-image v2 -- LAYA is the 2D->3D model: sheet transcription, CL shape program, native render comparison; no generator, no training
A scene.improve(domain:str, source:object, budget:object) -> receipt -- Shared core keeps a program edit only when model findings strictly shrink
P image-to-model(source, budget): scene.improve("laya3d", source, budget)
P sheet-to-models(): run scripts/laya3d_kronos.py -- private Blender background session on ports 49107/49108; writes D:/NeyviaRuns/laya-3d/kronos/out/summary.json
C image.verify objects: proof.objects >= 7 -- block every requested Kronos prop and both body targets were modelled
C image.verify improved: proof.improvedObjects == proof.objects -- block every object's mean same-camera outline IoU rose above its naive box baseline
C image.verify outline: proof.minimumMeanAfterIoU >= 0.85 -- block each model reprojects onto its fitted source views
C image.verify heldout: proof.meanHeldOutIoU >= 0.7 -- block leave-one-view-out silhouettes measure 3D shape, not reprojection
C image.verify kept: proof.keptEdits > proof.objects -- block the core kept program edits beyond the first hull
C image.verify reverted: proof.revertedEdits > 0 -- block the core rejected and restored non-improving edits
C image.verify sheet: proof.issuesRecorded > 0 -- block mislabeled, duplicate and illustration-only cells were found and stated
C image.verify illustration: proof.illustrationCellsUsed == 0 -- block topology guides, exploded and detail cells never become geometry
C image.verify speed: proof.maxSecondsPerObject <= 180 -- block per object end to end on the laptop, Blender startup excluded
C image.verify generator: proof.externalGenerators == 0 -- block LAYA generates the shape program locally
C image.verify cost: proof.paidCalls == 0 -- block no paid generation or labelling calls
C image.verify training: proof.training == false -- block episodes only; no fitting of model weights
C image.verify episodes: proof.episodes > 0 -- block kept and reverted outcomes are written to shared instant memory
F Fitted-view IoU is partly reprojection of the same masks; held-out IoU (camera refit, view left out of the hull) is the 3D measure.
F Silhouettes cannot recover concavities or hidden surfaces; thin parts seen only in three-quarter views are over-thick.
F Cameras are weak-perspective fits bounded by a declared coarse reading; captions are agent-read transcription, not OCR.
F Colour error compares 8-pixel regional colour; it does not score drifted AI detail as wrong colour.
