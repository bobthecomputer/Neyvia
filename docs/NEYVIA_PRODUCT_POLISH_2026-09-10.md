# Neyvia product polish — 10 September 2026

This pass applies the same interaction principles to conversations, tool activity, Preview and the built-in app workspaces: keep the work visible, put setup and evidence within reach, distinguish actual states, and remove repeated UI. It does not close the unfinished system ambitions in the [full feature checklist](NEYVIA_FEATURE_CHECKLIST_2026-09-10.md).

Implementation: `6c16489f167821f7cef57b54898382fd06c3418d`. Frontend manifest SHA-256: `1979c61dc67606776ba2b9559c044fb4d7f444b3d134b10568a7d51de8617f07`.

## Implemented and inspected

- [x] **One start screen:** orchestration keeps the familiar composer and adds agent/workflow controls. The chosen mode survives asynchronous startup.
- [x] **Readable conversations:** corrected doubled paragraph spacing, simplified message headers, removed repeated response labels, and reduced competing composer backgrounds.
- [x] **Shared run details:** both shells use the same compact receipt component. App, tool, command and runtime events have readable labels; structured inputs remain readable; older events and raw receipts remain accessible.
- [x] **Honest outcomes:** failed, uncertain and blocked states remain distinct. Artifact links come from recorded artifacts and reject unsafe URL schemes. Responses are not duplicated in the visible receipt.
- [x] **Visible activity:** an actual pending request shows Thinking and elapsed time even when the provider supplies no reasoning trace. Completion removes the indicator. Reduced-motion preferences are respected; there are no invented thoughts or progress percentages.
- [x] **Working nested controls:** selecting a message no longer swallows keyboard input intended for Run details or other controls.
- [x] **Usable Preview:** restored the desktop canvas height, expansion/restoration and phone overlay. The mobile stylesheet no longer hides an explicitly opened Preview.
- [x] **Device-centered app preview:** a running web app opens inside a portrait or landscape device canvas, with reload, expand/restore, open externally and direct interaction. Project/build setup is secondary and the preview remains mounted while status refreshes.
- [x] **Distinct app workspaces:** iOS Studio has a complete shared layout; image, audio, video, research and assessment apps retain appropriate canvases and controls. Studio routes resolve to their actual surfaces.
- [x] **Image editing correctness:** uploads retain source resolution; quarter-turn rotation swaps export dimensions. The decoded image is reused during adjustment. Invalid input reports an error and disables export; object URLs are released.
- [x] **Media and research actions:** verified audio play/pause, seeking, cue creation/export; video play/pause, cut metadata/frame export; source/claim persistence and notes export; assessment scope and report export.
- [x] **Less inert or duplicated UI:** removed inactive Notebook tabs, duplicate receipt markup/styles and obsolete tool-chip styling; repaired the Library prompt callback; simplified surface copy and secondary details.
- [x] **Cross-device state:** authenticated NAS candidate browsers preserve a draft, selected direction, correction and learning preference; stale checkpoint writes are refused.
- [x] **Harness and batch discovery:** the existing 16-entry catalog includes Hermes and OpenClaw. Preparation, cancellation before execution and saved-batch discovery work in the NAS candidate.

- [x] **Reliable startup and less repeated transfer:** content-addressed bundles are cached while entry HTML remains fresh. Missing assets return 404. A blocked startup module shows a working Reload action instead of an empty page. First PWA installation preserves the current interaction; replacing an existing worker reloads once.

## Evidence

The [screenshot gallery](../proof/product-polish-20260910/gallery.html) and [hashed packet](../proof/product-polish-20260910/packet.json) identify the inspected frontend. Local coverage contains 44 route/viewport entries, 26 interaction journeys and 115 passing Node frontend checks. The production build passes. Checks are recorded separately for the NAS candidate and deployed service.

Reproduction uses `npm run frontend:build`, the `npm run test:frontend`, `scripts/verify-product-polish-ui.mjs` and `scripts/verify-product-studios-ui.mjs`. `NEYVIA_PROOF_BASE` and `NEYVIA_PROOF_DIR` select the running host and output. Authentication is passed only through the protected `NEYVIA_PROOF_LOGIN` environment value. `NEYVIA_VIDEO_FIXTURE` supplies a disposable video. `scripts/verify-product-activity-ui.mjs` makes one explicitly bounded real Luna/medium request and is not part of the unit suite.

The NAS candidate reuses the existing environment identified by the dependency lock. Its 1,354 staged files were checked for missing, changed and extra files. Pre-existing local Tauri edits are preserved in WIP and excluded from this product release.

## Limits that remain visible

- The device canvas runs web applications. Native iOS execution still requires a Mac/Xcode environment; this release does not claim an iOS emulator on Windows.
- Phone screenshots and continuation checks use independent browser contexts with a narrow viewport, not a physical iPhone.
- A route that needs a selected task is only an entry-state check in the route sweep. Actual Preview interaction is covered by the selected-task journey.
- Fixture media proves the named upload/edit/export actions, not aesthetic quality or paid generation-provider integration. The click fixture proves that the embedded app receives input.
- Harness catalog visibility is not live execution of every adapter or integration of every upstream Hermes training feature.
- Removed duplication is scoped to the changed UI. The entire repository has not been proven free of dead code or optimal in performance.
- The wider programme still needs universal recovery, physical-device execution, the precise-image/taste loop, the game make-and-test journey and controlled model-quality/performance comparisons.

Published NAS `current`: `neyvia-candidate-20260910-101928-product-polish`. The previous `neyvia-candidate-20260910-072634-system-improvement` remains available for rollback. The deployed frontend manifest matches the local build, all 1,354 candidate files remain unchanged after activation and inference, and a real Luna/medium request completed in 14.109 seconds with visible Thinking before any trace. The live conversation and startup/recovery journeys also pass.

See the [publication receipt](../proof/product-polish-20260910/nas-publication.json), [live request receipt](../proof/product-polish-20260910/nas-activity/receipt.json) and [post-deployment integrity check](../proof/product-polish-20260910/nas-deployed-integrity.json). Source, WIP, candidate and public `current` remain distinct.
