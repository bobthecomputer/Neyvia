# NEYVIA reconciliation and continuation status, 22 July 2026

This record continues the completed 54-step overnight operator ledger. It does not invent an OP-055 or reopen a checked item.

## Recovered sources

- Desktop working tree: `C:\Users\example\projects\vibe-coding-platform`
- Harness release task: Codex task `019f80a1-5c56-72f1-bd1d-323febc2b277`
- Sealed Harness candidate: `syntelos/releases/neyvia-candidate-20260721T005035Z` (289 files)
- Later conversation candidate: `syntelos/releases/neyvia-candidate-20260721T153424Z-conversation-fabric` (406 files)
- Reconciled immutable candidate: `syntelos/releases/neyvia-candidate-20260721T224348Z-reconciled-fabric`

The reported second version was not a hidden Git branch. All auxiliary worktrees were clean at commit `46b07c2`; the conflicting implementation was recoverable from the local Codex task record and the two immutable NAS candidates.

## Reconciliation decisions

Kept from the Harness release:

- enforced read-only chat mirrors and configured workspace execution boundaries;
- durable Harness jobs, cancellation receipts, process identity checks, and secret-free profiles;
- serialized lease claims, bounded worker concurrency, startup gates, watchdog readiness, and sealed-release worker imports;
- the first-class Harness control surface and its seven-runtime catalog;
- PWA registration and removal of the external Google Font startup dependency.

Kept from the later conversation tree:

- SQLite conversations, MCP/coordinator/model-catalog work, exact history selection, and orchestration selection;
- scheduler scanning beyond fifty incompatible jobs and accurate live host load reporting;
- newer Cursor, Hermes, OpenClaw, and OpenCode provider/model normalization;
- current project navigation, PWA source assets, and later regression tests.

Rejected from the merge:

- obsolete hashed frontend bundles, logs, caches, process state, and temporary browser artifacts;
- stale backend/runtime files that removed proven Harness contracts;
- any change to the public `syntelos/current` release.

## Completed continuation slice

- A clicked conversation loads the exact durable SQLite transcript or orchestration graph.
- Historical browsing is explicit and read-only; the composer returns only after `Return to current work`.
- Newly sent Agent turns persist with the exact legacy turn IDs, optimistic revisions, and provenance metadata.
- Runtime replies persist after the real dispatch. An identical replay returns the stored result without calling the model twice.
- A conflicting reused turn ID fails closed instead of overwriting a transcript.
- Direct Harness chat uses an isolated source mirror; only an executor lane in orchestration can receive write mode.
- The Harness page is restored as a real navigation destination with its durable queue and runtime controls.

## Verification

- `228 passed`: backend, runtime adapters, Harness safety, scheduler/concurrency, launcher contract, worker repair, and conversation persistence.
- `13 passed`: focused SQLite conversation, backend replay, and exact navigation contracts.
- PWA contract and `npm run verify:pwa` pass.
- `npm run frontend:build` passes. The existing Vite chunk-size warning remains informational.
- Detached Playwright proof passes without the Codex embedded browser: exact transcript, hidden historical composer, restored live composer, seven Harness runtime choices, and zero console/page errors.
- Proof: `.agent_control/runtime_proof/neyvia-conversation-fabric-headless.json` and `.png`.

## Release boundary

The new candidate was staged, hash-verified, and atomically finalized on the NAS as transfer `nas_batch_20260722_005014_2dec7d45`:

- candidate: `syntelos/releases/neyvia-candidate-20260721T224348Z-reconciled-fabric`;
- verified tree: 451 files, 18,366,939 bytes, SHA-256 `a7716bede214bf6bca847dc2cd78761558103605fe25bd28e00ba5f46f05d788`;
- completion proof SHA-256: `95c6b3cb1c3c9303b30d51b01407d1429e4cb5d97c693e48cd4ca089637afcfa`;
- local receipt: `.agent_control/nas_transfers/nas_batch_20260722_005014_2dec7d45.json`;
- NAS receipt: `.agent_control/neyvia_transfers/receipts/nas_batch_20260722_005014_2dec7d45.json`.

An independent read verified that the local and NAS receipts are identical, the completion proof and receipt authenticate the same tree, and no incomplete staging sibling remains. The public/live `syntelos/current` tree and marker hashes were identical before and after transfer; it still references `neyvia-candidate-20260721T153424Z-conversation-fabric`. Publication remains a separate operator decision.

Publication note: local account paths and network identifiers in this document are neutral examples.
