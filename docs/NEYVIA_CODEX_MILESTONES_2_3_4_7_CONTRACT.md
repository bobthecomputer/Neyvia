# Neyvia Codex completion contract

This document is the handoff boundary between Codex and Opus 5. It describes
the stable interfaces Opus may consume while completing marketplace and final
acceptance work.

`OXIR` / `OSIR` is not a product requirement. No verified repository or package
identity exists for that name, so it was removed rather than guessed.

## Milestone 2: progressive first run

Backend commands:

- `get_progressive_setup_command`
- `update_progressive_setup_command`

Contract: `neyvia.first_run.v1`

The contract has exactly three stages:

1. Essential setup
2. Recommended integrations
3. Advanced capabilities

The shell can open with no optional CLI. Starting a model-backed mission remains
blocked until an account or runtime is ready and permissions have been reviewed.
All selections are resumable from
`.agent_control/neyvia/first_run.json`.

The existing detailed onboarding doctor remains available. Its payload now also
contains `progressiveSetup`; it was not replaced.

## Milestone 3: one runtime execution path

The authoritative executor remains:

- `run_runtime_invocation_turn_command`
- `FluxioWebBackend._run_runtime_invocation_turn`
- `neyvia.runtime.invocation.v1`

The old managed-CLI message action now opens or reuses a durable inline
invocation and calls that executor. It no longer returns
`queued_not_executed`.

Returned transcript entries include:

- the real user message;
- real assistant content;
- real provider tool events;
- runtime, model, stable external session identity when supplied;
- sequence and provenance;
- changes, artifacts, and receipts.

Every frontend request supplies an idempotency key. A completed key is suppressed
after restart instead of repeating the provider turn.

## Milestone 4: selective context import

Backend commands:

- `get_context_import_sources_command`
- `preview_context_import_command`
- `import_context_selection_command`
- `list_context_imports_command`

Contracts:

- `neyvia.context_import.v1`
- `neyvia.context_import.preview.v1`
- `neyvia.context_import.receipt.v1`

Supported source labels are Codex, Claude Code, OpenCode, Hermes, and OpenClaw.
The stable input is a user-selected JSON, JSONL, Markdown, or text export.
Neyvia does not scrape provider databases or import all history automatically.

Preview reports source hash, item identity, approximate size, roles,
attachments excluded by default, and credential redactions. Import requires an
explicit item selection and rechecks the source hash. Imported content and its
lineage are stored under `.agent_control/neyvia/context_imports/`.

Codex configuration, instruction, skill, and plugin metadata continue to use the
existing `CodexAssetImporter`; the provider-neutral context path does not replace
it.

## Milestone 7: durable mission continuity

Backend commands:

- `get_mission_continuity_command`
- `checkpoint_mission_continuity_command`
- `record_continuity_tool_attempt_command`
- `decide_continuity_retry_command`
- `recover_mission_continuity_command`
- `evaluate_gpu_policy_command`
- `get_mission_operator_update_command`

Primary contract: `neyvia.mission_continuity.v1`

Durable state includes goal, plan, current step, last completed step, confirmed
facts, artifacts, tool attempts, latest safe checkpoint, approval or user input,
next action, failure, and recovery information.

The shared policy provides:

- idempotency receipts;
- bounded retry decisions;
- justified alternative routing;
- proportional verification;
- restart and compaction recovery;
- configurable GPU concurrency, cost, duration, and idle limits;
- approval requirements for paid or destructive GPU work;
- calm operator updates rather than raw event noise.

Runtime invocation turns checkpoint through this contract. Thunder Compute
browser execution consumes the GPU decision when a mission identity is supplied
and records its verified result back into continuity.

Opus should consume these commands and schemas. It should not create parallel
continuity, transcript, context-import, or GPU-policy stores.
