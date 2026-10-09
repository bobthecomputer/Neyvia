---
name: neyvia-image-studio
description: "Use when editing or exporting images in Neyvia's Image Studio (crop, resize, composite, export)."
---

Use `cl(lines="...")` for CL 1.1 calls. Start with the layer index below;
`help("layer")` loads signatures on demand. Prefer `run layer.procedure(...)`.
The host fills stamps and handles, checks effects, and preserves existing approvals.
Finish with `done("summary")`; it succeeds only after the observed task goal passes.
The existing PORTED.md scope remains discoverable.

<!-- Generated from manuals/cl/image-studio.cl by scripts/build_claude_plugin_skills.py; edit the CL source. -->

L efficiency v2 -- Validated script/memory/System 1/cache/Luna/Sol routing,
L sidebar v2 -- Transcript agent trees, event-based lanes and local semantic preview/confirm/undo
L cua v2 -- Background native app driver, live preview, takeover and approvals
L agent-view v2 -- Watch and steer agents on their own surfaces: live mirror, comments bound
L neyvia v2 -- Sidebar, projects, sessions, scheduling, runtime and missions
L neyvia-reference v2 -- Detailed sessions, projects, panes, time, runtime, missions and
L workspace v2 -- Scoped files, hashes, diffs, terminal and receipts
L pdf v2 -- PDF shared state, pages, search, highlights and extraction
L notes v2 -- Markdown notes folder: list, search, tags, pins, safe writes
L files v2 -- File explorer places, quick look, move, Recycle Bin and undo
L image-studio v2 -- Real pixel edits, protected regions, export and explicit provider generation
L mobile-studio v2 -- Phone preview of a web app with hot reload, plus iPhone
L hill-climb v2 -- Frozen improvement receipts, history and measured Pareto tradeoffs
L awareness v2 -- Work board (who changes which files), impact map, intent checklist
L working-with-paul v2 -- Reading Paul's dictated requests, what done means, style, release
L onboarding v2 -- First run: base pack download, agents found on this PC, interests,
L agents v2 -- Agents dashboard, checklists and plan limits
L cross-pc v2 -- Paired PCs: shared paths, bounded reads, inbox sends and
L tools-depth v2 -- Ripgrep, guarded range edits and cached web passages with citations
L design v2 -- Neyvia's look: tokens, four themes, primitives, motion,
L manuals-next v2 -- Durable state handles, deltas, verified scripts, version lineage and bound
L dictation v2 -- Prompt dictation: live words, spoken commands, language routing, names
L autopilot v2 -- Intent-driven scoped runs with executable per-ask receipts
L outputs v2 -- Publish and reopen real files, diffs, images, reports and receipts;
L conductor v2 -- Goal to routed task tree, review, durable execution and verifier receipts
L perception v2 -- Structured text, handles and diffs for OS, windows, browser,
L game-dev v2 -- Native game editor bridges, exact sessions, durable action receipts and checked
L nightshift v2 -- Night Shift task tree in the Canopy: create/import, prerequisites,
L transparency v2 -- Uniform provider reasoning, full commands and results, diffs, and durable thread
L handoff-recovery v2 -- Reviewed handoff intake, stale-write reconciliation, judgement stops and
L mission-plan v2 -- Sectioned plan, separate worktrees, Claude builders, Codex verification
L slim-installer v2 -- Signed base-pack release receipts, local proof limits and production authority gates
L remote v2 -- Owner-enabled, guarded live remote windows with native host Stop and no recording
L browser v2 -- Shared WebView2 browser and non-stealth Obscura task promotion
L app-sdk v2 -- CL1.1 app generation, shared state/actions, Mobile preview,
L scroll-generator v2 -- Source-bound Scroll Study generation, review, pack validation, costs and executable
L voice v2 -- Voice commands, shared UI bus and owner-scoped approvals
L settings v2 -- Canonical preferences, proposals, local-only enforcement and setup
L creativity v2 -- Executable creativity workflow with host-bound evidence and Evolver quality/adherence fitness
L critique-review v2 -- Executable critique-review workflow with host-bound evidence and Evolver
L research v2 -- Executable research workflow with host-bound evidence and Evolver quality/adherence fitness
L proofs v2 -- Host contracts, isolated startup procedures, coverage and guarded test retirement
L proofs-b-desktop v2 -- Desktop reports, durable delivery journals, document ingestion and gateway contracts
L proofs-b-engine v2 -- Local ecosystem, engine, routing, recorder and watchdog action contracts
L proofs-b-adapters v2 -- Git objects, release staging, OCR repair, handoffs and
L proofs-b-harness v2 -- Durable harness admission, job lifecycle, execution slots and runtime-budget
L proofs-b-browser v2 -- PROOFS-b real Chrome blocked-run cleanup and capacity waiting display
L host-runtime v2 -- Host event identities, scoped remote transport, skill provenance and stage/delta
L neyvia-core v2 -- Prompt profiles and application runtime semantic contracts
L native-runtime v2 -- Native durable state, authority and execution semantic contracts
L ui-planning v2 -- PROOFS-d ui-planning real-action semantic contracts
L runtime-provider v2 -- PROOFS-d runtime-provider real-action semantic contracts
L nearby-send-runtime v2 -- Nearby Send byte-stream integrity, truthful cancellation and durable resume contracts
L inception v2 -- Pinned scratch Neyvia drives candidate journeys through T16/T18 with complete
L language v2 -- No-slop words in UI and reports: dashes, hype,
L native-applications v2 -- Owned hidden Office native fields, save/reopen checks and grounded learned
L adaptive-work v2 -- Persist focus, problems and constraints under one work identity with exact revision checks
L creative-records v2 -- Exact local task proposals and bounded caller-reported attention experiment records
L local-records v2 -- Exact local records and declared artifact measurements
L local-integrity v2 -- Local work initialization and independent proof artifact integrity
L local-mechanisms v2 -- Frozen local laboratory measurements and protected context compaction
L local-environment v2 -- Scoped saved scripts and exact declared output artifacts
L local-app-open v2 -- Fresh mounted content acknowledgements for local app and artifact files
L local-evaluations v2 -- Fresh questions, artifact obligations, frozen curricula, trace and pixel
L local-host v2 -- Fresh owned managed-process and explicit plugin byte effects
L local-media v2 -- Fresh browser captures, measured taste reports, video artifacts and atomic skill revisions
L local-rendering v2 -- Fresh mounted DOM effects for shell, Notes, setup and bounded spoken
L local-evolver v2 -- Real frozen paired manual compiler compression, seeded cases and independent heldout
L local-browser-sdk v2 -- Actual private DOM sessions, mounted SDK preview, source-bound SDK goals
L research-assistant v2 -- Public Search, Obscura, LAYA and validated research cascade
L memory v2 -- Private project/user cue memory, explicit corrections, forgetting and bounded local recall
L edge-contracts v2 -- Generated adversarial contract cases, isolated real journeys and explicit uncovered edges
L C7e-pure v2 -- Generated pure cases with strict family pass and current source checks
L C7e-frontend v2 -- Generated frontend cases with strict family pass and current source checks
L C7e-preferences-skills v2 -- Generated preferences-skills cases with strict family pass
L C7e-ui-remaining v2 -- Generated ui-remaining cases with strict family pass and
L C7e-c7d-rendered v2 -- Generated c7d-rendered cases with
L C7e-c7d-control v2 -- Generated c7d-control cases with strict family
L C7e-local-completion v2 -- Generated local-completion cases with strict family pass,
L C7e-mission-completion v2 -- Generated mission-completion cases with strict family
L C7e-c7d-ui v2 -- Generated c7d-ui cases with strict family
L C7e-c7d-ui-control v2 -- Generated c7d-ui-control cases with
L C7e-c7d-verification v2 -- Generated c7d-verification cases with
L C7e-c7d-wz v2 -- Generated c7d-wz cases with
L C7e-c7d-ui-settings v2 -- Generated c7d-ui-settings cases with
L C7e-c7d-engine v2 -- Generated c7d-engine cases with strict family
L C7e-c7d-control-completion v2 -- Generated c7d-control-completion
L C7e-c7d-provider-marks v2 -- Generated c7d-provider-marks
L C7e-native-completion v2 -- Generated native-completion cases with strict family pass,
L C7e-c7d-providers v2 -- Generated c7d-providers cases with
L C7e-c7d-adapters v2 -- Generated c7d-adapters cases with
L C7e-c7d-projection v2 -- Generated c7d-projection cases with
L C7e-c7d-desktop v2 -- Generated c7d-desktop cases with
L C7e-capability-completion v2 -- Generated capability-completion cases with strict family
L C7e-session-completion v2 -- Generated session-completion cases with strict family pass,
L C7e-host-actions-completion v2 -- Generated host-actions-completion cases with strict family
L C7e-c7d-native-commands v2 -- Generated c7d-native-commands
L C7e-local v2 -- Generated local cases with strict family pass, source freshness and receipt
L C7e-scheduler v2 -- Generated scheduler cases with strict family pass, source freshness and
L C7e-capabilities v2 -- Generated capabilities cases with strict family pass, source freshness and
L C7e-mobile v2 -- Generated mobile cases with strict family pass, source freshness and receipt
L C7e-providers v2 -- Generated providers cases with strict family pass, source freshness and
L C7e-native v2 -- Generated native cases with strict family pass, source freshness and receipt
L C7e-surfaces v2 -- Generated surfaces cases with strict family pass, source freshness and
L C7e-models v2 -- Generated models cases with strict family pass, source freshness and
L C7e-missions v2 -- Generated missions cases with strict family pass, source freshness and
L C7e-engine v2 -- Generated engine cases with strict family pass, source freshness and receipt
L C7e-control v2 -- Generated control cases with strict family pass, source freshness and receipt
L C7e-sessions v2 -- Generated sessions cases with strict family pass, source freshness and
L C7e-chat-shell v2 -- Generated chat-shell cases with strict family pass, source freshness
L C7e-host-runtime v2 -- Generated host-runtime cases with strict family pass, source freshness
L C7e-core v2 -- Generated core cases with strict family pass, source freshness and receipt
L C7e-artifact-manual v2 -- Generated artifact-manual cases with strict family
L C7e-control-remaining v2 -- Generated control-remaining cases with strict family pass,
L C7e-capability-models v2 -- Generated capability-models cases with strict family
L C7e-ui-planning-local v2 -- Generated ui-planning-local cases with strict family
L modules v2 -- Module map, source browser and optional mods
L hyperframes v2 -- HyperFrames (HeyGen) HTML video compositions rendered headless for agents
L filmcraft v2 -- FilmCraft headless editor for agents: sequence Scene, edits, export
L effectcraft v2 -- EffectCraft headless compositor for agents: comps, layers, frames,
L photocraft v2 -- PhotoCraft headless image editor for video frames
L hello-module v2 -- A real optional personal greeting mod
L laya-glance v2 -- Shared Scene core, UI defect vocabulary and instant episodic admission
L coverage-ratchet v2 -- Monotonic release coverage debt and separate static web journey evidence
L video v2 -- HyperFrames video editing through EDLs, LAYA video observers, predicates
L documents v2 -- Paul's study-document template: create, Tectonic build, outcome checks,
L connections v2 -- Connections: every harness, key and local model with honest state, one-click
L usage v2 -- Usage screen: plan windows, tokens by day, agent and model,
L parallel v2 -- Parallel Git worktrees, connected workers, inbox questions, ordered merge conflict resolution
L comments v2 -- Pinned workspace comments, anchored connected-session delivery and verified resolution
