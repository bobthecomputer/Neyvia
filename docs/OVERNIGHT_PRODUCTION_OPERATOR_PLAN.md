# Fluxio Overnight Production Operator Plan

This document is the source of truth for the next architecture push.

The automation rule is simple:

1. Read this file.
2. Count checked and unchecked implementation ledger items.
3. Start with the first unchecked item.
4. Implement it with the smallest real change that moves the architecture forward.
5. Add proof under that item.
6. Mark it checked only when the proof exists.

Do not treat chat history as the source of truth. Update this file when the plan changes.

## North Star

Fluxio should become an overnight production operator, not a desktop helper.

Fluxio should let the operator say:

```text
Work on these missions tonight. Use these keys, these skills, these limits.
Prove before starting that you are ready.
If my PC is awake, use it for heavy/browser/build work.
If not, keep going on the NAS.
In the morning, show me exactly what finished, what failed, and what needs me.
```

The NAS is not a weak fallback. It is the always-on mission engine.

The PC is not required for correctness. It is a burst accelerator for heavy/browser/build work.

## Core Beliefs

- Fluxio must be trustworthy before it is clever.
- Mission truth must live in durable receipts, not optimistic UI state.
- The NAS must keep working when the operator PC sleeps.
- The PC gateway should accelerate jobs automatically when it is awake.
- Planner, executor, and verifier should be phases inside one supervised mission runtime.
- Compact receipts should move between phases instead of giant context dumps.
- Python unit tests are useful for contracts, but mission proof should come from real command, UI, artifact, and verifier receipts.
- No mission should fake progress. Queued, blocked, partial, and failed states are valid outcomes.

## Target Architecture

### One Mission Envelope

Every mission runs inside one `MissionRun` envelope.

The envelope owns:

- mission id
- original goal
- workspace id
- file scope
- selected runtime
- selected skills
- host lease
- process tree
- phase state
- event stream
- proof artifacts
- compact receipts
- final morning report row

There should not be separate fake agents competing over mission state.

### One Runtime Flow

The runtime flow is:

```text
Preflight -> Planner -> Executor -> Verifier -> Repair -> Final Report
```

The phases are sequential by default.

Planner produces a plan.
Executor executes the plan.
Verifier proves or rejects the result.
Repair runs only when verifier says repair is needed.
Final report summarizes truth.

### Planner Phase

The planner receives:

- original goal
- workspace facts
- available skills
- runtime capability summary
- constraints
- prior failed receipts, if any

The planner produces `PlanReceipt`.

`PlanReceipt` must include:

- goal restatement
- assumptions
- tasks
- file scope
- selected skills
- forbidden paths or actions
- expected changed files
- expected artifacts
- verification ladder
- risk level
- maximum repair loops

The planner should not continue indefinitely.

### Executor Phase

The executor receives only:

- original goal
- compact plan receipt
- selected skills
- file scope
- current workspace facts

The executor produces `ExecutionReceipt`.

`ExecutionReceipt` must include:

- tasks attempted
- tasks completed
- changed files
- commands run
- stdout/stderr summaries
- errors encountered
- skipped work
- self-critique
- next suggested verifier checks

The executor should not mark the mission complete.

### Verifier Phase

The verifier receives:

- original goal
- plan receipt
- execution receipt
- changed files
- proof artifacts
- verification command ladder

The verifier produces `VerificationReceipt`.

`VerificationReceipt` must say one of:

- `accepted`
- `repair_needed`
- `blocked`
- `operator_needed`

It must also say:

- what passed
- what failed
- what was not tested
- what evidence was inspected
- whether the final state satisfies the original goal

### Repair Phase

Repair is not another open-ended mission.

Repair receives:

- verifier failure summary
- original goal
- plan receipt
- execution receipt
- changed files

Default policy:

- one repair loop
- bounded file scope
- no broad replanning unless verifier requests it
- no repeated giant context

Repair produces `RepairReceipt`.

### Final Report Phase

The final report produces `FinalProofReceipt`.

It must include:

- final mission status
- receipts produced
- changed files
- commands run
- artifacts
- verification result
- proof gaps
- operator actions needed
- follow-up work

## Night Mode

Night mode is a first-class run profile.

It should not mean "safe maintenance only."

It should mean:

```text
Run production missions overnight with proof, low resource usage, truthful state, and bounded risk.
```

### Night Readiness

Before work starts, Fluxio must create `NightReadinessReceipt`.

It verifies:

- NAS worker is alive
- runtime auth is available
- selected runtime exists
- selected skills are available
- workspace path exists
- Git state is understood
- disk pressure is safe
- RAM/swap pressure is safe
- process registry is clean enough
- model/provider keys exist, masked
- mission queue can run
- notification channel is configured or explicitly skipped
- desktop gateway status is known

If readiness fails, Fluxio does not start the night run.

It sends a clear message:

```text
Night run did not start because: <reason>.
```

### Night Run Queue

The night queue should prefer:

1. blocked mission reconciliation
2. small repair loops
3. headless executor work
4. headless verifier work
5. proof compaction
6. morning digest generation

The night queue should defer:

- browser verification if no PC gateway is online
- full frontend builds if NAS pressure is high
- destructive Git actions
- package upgrades without explicit approval
- any command outside the leased workspace scope

## NAS And PC Gateway

### NAS Role

The NAS is:

- controller
- storage authority
- mission store
- scheduler
- artifact index
- receipt store
- watchdog
- efficient executor
- night mode runner

The NAS should run one worker process by default.

The NAS can execute:

- planning
- file edits
- small command checks
- headless runtime work
- mission reconciliation
- proof compaction
- morning digest

The NAS should not execute by default:

- browser automation
- Playwright
- heavy frontend builds
- GPU/model-local work
- broad full-suite test loops

### PC Gateway Role

The PC gateway is:

- burst accelerator
- browser verifier
- frontend build runner
- visual/UI smoke runner
- heavy runtime worker

When PC is awake:

- desktop gateway heartbeats to NAS
- NAS routes browser/build/heavy verifier jobs to PC
- PC streams events back
- NAS remains source of truth

When PC sleeps:

- NAS keeps going
- browser/build jobs become queued proof gaps
- missions can still complete if headless verifier proof is sufficient
- missions do not fake completion if proof is missing

## Efficiency Strategy

The NAS is low performance. Optimize the system, not just the hardware.

Use:

- SQLite WAL event store
- append-only event log
- compact mission snapshots
- bounded stdout/stderr tails
- content-addressed context capsules
- file hash receipts
- incremental Git diff scanning
- one worker process by default
- adaptive verification ladder
- selective context loading
- no repeated giant prompt dumps
- no full repo context unless needed
- no giant Python suite as the default proof

### Context Capsules

Each phase gets a capsule.

Planner capsule:

- original goal
- workspace facts
- relevant docs
- skill brief
- current queue state

Executor capsule:

- original goal
- plan receipt
- selected skills
- file scope
- known constraints

Verifier capsule:

- original goal
- plan receipt
- execution receipt
- changed file list
- proof artifacts
- command ladder

Capsules should be content-addressed and stored under `.agent_control`.

### Adaptive Verification Ladder

Default verification order:

1. syntax/import checks
2. changed-file targeted checks
3. command smoke
4. backend command smoke
5. UI/button smoke if available
6. frontend build only when capacity allows
7. browser verification only on PC gateway or approved NAS mode
8. full suite only when explicitly selected

Each rung produces a receipt.

The verifier can accept with proof gaps only when the gaps are explicit and not required for the goal.

## Proof System

Every mission should produce:

- readiness receipt
- plan receipt
- execution receipt
- verifier receipt
- changed-file receipt
- command receipt
- artifact receipt
- blocked receipt, if blocked
- final morning report row

The UI should show proof, not narration.

Every receipt should include:

- schema
- receipt id
- mission id
- generated at
- phase
- host
- runtime
- workspace
- status
- summary
- inputs
- outputs
- proof paths
- next action

## Messaging

Fluxio should send messages for:

- night run started
- mission completed
- mission blocked
- approval needed
- PC gateway connected
- PC gateway disappeared
- NAS pressure high
- verifier proof gap
- morning digest ready

Channels:

- browser inbox
- desktop gateway
- Telegram
- ntfy
- web push
- local `.agent_control` digest

Messages should be short.

Each message links to a receipt or digest.

## Runtime Wrapping

Hermes, OpenClaw, OpenCode, and Codex should run as external supervised processes.

Fluxio controls:

- cwd
- environment
- runtime home
- timeout
- stdout tail
- stderr tail
- process tree
- heartbeat
- receipts
- termination
- replay

Fluxio should supervise runtimes. It should not pretend to be the runtime.

Runtime wrapper outputs:

- event stream
- phase receipt
- final exit status
- changed file receipt
- artifact receipt

## Skill System

Before planning, Fluxio builds `SkillBrief`.

`SkillBrief` includes:

- matching installed skills
- repo-specific skills
- allowed tools
- forbidden areas
- relevant examples
- constraints
- known failures
- prior successful recipes

Planner picks skills.
Executor uses them.
Verifier checks whether skill use was relevant.

Skills should be selected for the task, not loaded blindly.

## Sub-Agent System

Sub-agents are not random extra agents.

Use them for:

- isolated research
- review
- diagnostics
- parallel file inspection
- UI verification
- log summarization

Sub-agents return receipts, not giant prose.

Sub-agent receipt fields:

- assignment
- inputs
- files inspected
- findings
- confidence
- proof paths
- next recommendation

## Debugger And Flight Recorder

Every mission gets a flight recorder.

It stores:

- last 200 events
- current phase
- runtime command
- cwd
- env status, masked
- process ids
- lease id
- heartbeat age
- queue reason
- stdout tail
- stderr tail
- changed files
- verifier result
- next recovery action

When broken, Fluxio should explain:

- what failed
- where it failed
- why it likely failed
- what proof exists
- what to do next

The debugger should be exceptional when the system is deeply broken:

- collect registry snapshot
- collect process tree
- collect mission receipts
- collect runtime session files
- collect queue state
- write one diagnostic bundle

## UI Direction

Keep one focused mission shell.

Do not turn Fluxio into a dashboard grid.

Center lane:

- active mission
- current phase
- current focused task
- proof timeline
- latest runtime output

Right rail:

- approvals
- runtime health
- NAS/PC capacity
- verifier status
- proof gaps
- next safe action

Left rail:

- workspaces
- missions
- recent runs
- inbox

The operator should know in under five seconds:

- what is active
- what is happening
- whether approval is needed
- what proof exists
- what happens next

## Testing And Verification Philosophy

Avoid huge Python tests as the primary proof.

Use Python tests for:

- pure contract logic
- receipt schema parsing
- scheduler decisions
- lease expiry
- reaper dry-run logic

Use functional proof for:

- buttons
- backend commands
- mission launch
- worker claim
- runtime process execution
- UI state
- artifact generation

Preferred proof:

- small command receipts
- focused CLI smoke
- backend command response
- UI click smoke
- final mission proof receipt

## Implementation Ledger

Automation should count these lines.

When a step is done:

1. change `[ ]` to `[x]`
2. add a `Proof:` line
3. add changed files
4. do not reorder completed steps

### Phase 0 - Existing Foundation Already Landed

- [x] OP-001 Add SQLite cluster registry for hosts, jobs, leases, events, artifacts, and managed processes.
  Proof: `tests/test_cluster_scheduler.py` passes; cluster registry exposes scheduler and process lifecycle APIs.
  Files: `src/grant_agent/cluster.py`, `tests/test_cluster_scheduler.py`

- [x] OP-002 Add worker process that can claim local or controller jobs and emit lifecycle events.
  Proof: fake worker claim/complete test passes in `tests/test_cluster_scheduler.py`.
  Files: `src/grant_agent/worker.py`, `tests/test_cluster_scheduler.py`

- [x] OP-003 Add process registry, dry-run reaper, and architecture doctor.
  Proof: `process-reaper --dry-run` returns bounded JSON and no kill actions by default.
  Files: `src/grant_agent/cluster.py`, `src/grant_agent/cli.py`

- [x] OP-004 Make NAS efficient execution policy explicit.
  Proof: NAS worker doctor reports `runtime.launch` and `nas.efficient`; browser/build capabilities are excluded in efficient mode.
  Files: `src/grant_agent/cluster.py`, `src/grant_agent/runtime_supervisor.py`, `package.json`

- [x] OP-005 Add worker CLI shortcuts and NAS setup guidance.
  Proof: `npm run nas:worker:doctor` passes locally and prints Example NAS NAS-efficient capabilities.
  Files: `package.json`, `scripts/run_grant_agent_cli.py`, `scripts/nas_setup.py`

### Phase 1 - MissionRun Envelope

- [x] OP-006 Define `MissionRun` data model.
  Proof: Added `fluxio.mission_run.v1` envelope dataclasses for mission run state, phase state, process refs, and compact receipt refs. Verified with `python -m py_compile src/grant_agent/models.py` and `$env:PYTHONPATH='src'; python -m pytest tests/test_mission_run_model.py -q` (`3 passed`).
  Files: `src/grant_agent/models.py`, `tests/test_mission_run_model.py`

- [x] OP-007 Define receipt schemas: `NightReadinessReceipt`, `PlanReceipt`, `ExecutionReceipt`, `VerificationReceipt`, `RepairReceipt`, `FinalProofReceipt`.
  Proof: Added typed receipt dataclasses with explicit `fluxio.*_receipt.v1` schema names, common mission proof fields, phase-specific fields, and verifier decisions. Verified with `python -m py_compile src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_run_model.py tests\test_mission_receipt_schemas.py -q` (`6 passed`).
  Files: `src/grant_agent/models.py`, `tests/test_mission_receipt_schemas.py`

- [x] OP-008 Add receipt writer/reader with schema validation and bounded retention.
  Proof: Added `mission_receipts` JSONL writer/reader with schema validation, corrupt-row skipping, mission filtering before limits, and capped retention. Verified with `python -m py_compile src\grant_agent\models.py src\grant_agent\mission_receipts.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_receipt_schemas.py tests\test_mission_receipt_store.py -q` (`7 passed`).
  Files: `src/grant_agent/mission_receipts.py`, `tests/test_mission_receipt_store.py`

- [x] OP-009 Add one mission artifact directory layout under `.agent_control/mission_runs/<mission_id>/`.
  Proof: Added a path-safe mission run artifact layout helper for receipts, events, artifacts, proof, logs, capsules, runtime, reports, and snapshots under `.agent_control/mission_runs/<mission_id>/`, plus proof that receipt storage can target the per-mission receipt path. Verified with `python -m py_compile src\grant_agent\mission_artifacts.py src\grant_agent\mission_receipts.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_artifacts.py tests\test_mission_receipt_store.py tests\test_mission_receipt_schemas.py -q` (`11 passed, 4 subtests passed`).
  Files: `src/grant_agent/mission_artifacts.py`, `tests/test_mission_artifacts.py`

- [x] OP-010 Add migration/read-model bridge so existing `missions.json` can display `MissionRun` state without a full migration.
  Proof: Added `missionRun` to mission detail snapshots as a bounded read model derived from legacy `missions.json`, per-mission artifact layout paths, optional `mission_run.json` snapshots, and real per-mission receipts without rewriting `missions.json`. Verified with `python -m py_compile src\grant_agent\models.py src\grant_agent\mission_receipts.py src\grant_agent\mission_artifacts.py src\grant_agent\mission_control.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_receipt_schemas.py tests\test_mission_receipt_store.py tests\test_mission_artifacts.py tests\test_mission_control.py -q -k "mission_receipt or MissionArtifactLayoutTests or mission_run_read_model or per_mission_receipts"` (`13 passed, 159 deselected, 4 subtests passed`).
  Files: `src/grant_agent/mission_control.py`, `tests/test_mission_control.py`

### Phase 2 - Phase Runner

- [x] OP-011 Implement phase runner state machine: preflight, planner, executor, verifier, repair, final_report.
  Proof: Added `mission_phase_runner` state transitions for starting and completing MissionRun phases, accepted verifier flow to final report, repair-needed flow through one repair phase, blocked/failed terminal handling, receipt attachment, and restart guards. Verified with `python -m py_compile src\grant_agent\mission_phase_runner.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_runner.py tests\test_mission_run_model.py -q` (`7 passed`).
  Files: `src/grant_agent/mission_phase_runner.py`, `tests/test_mission_phase_runner.py`

- [x] OP-012 Make planner produce compact `PlanReceipt`.
  Proof: Added `build_docs_first_plan_receipt` so the existing docs-first planner emits a compact `PlanReceipt` with bounded tasks, assumptions, file scope, selected skills, forbidden paths, expected artifacts, verification ladder, risk level, and no embedded large docs. Verified with `python -m py_compile src\grant_agent\planner.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_planner.py tests\test_mission_receipt_schemas.py -q` (`6 passed`).
  Files: `src/grant_agent/planner.py`, `tests/test_planner.py`

- [x] OP-013 Make executor consume only goal, plan receipt, selected skills, and file scope.
  Proof: Added `ExecutorPhaseInput` and `build_executor_phase_input` so executor phase input is limited to the original goal, a compact PlanReceipt, selected skills, and file scope, explicitly dropping raw docs, inputs/outputs, metadata, mission history, and other context noise. Verified with `python -m py_compile src\grant_agent\mission_phase_inputs.py src\grant_agent\planner.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_inputs.py tests\test_planner.py -q` (`6 passed`).
  Files: `src/grant_agent/mission_phase_inputs.py`, `tests/test_mission_phase_inputs.py`

- [x] OP-014 Make verifier consume goal, plan receipt, execution receipt, changed files, and proof artifacts.
  Proof: Added `VerifierPhaseInput` and `build_verifier_phase_input` so verifier context is limited to the original goal, compact PlanReceipt, compact ExecutionReceipt, changed files, and proof artifacts, with schema validation, dedupe, and bounded command/output summaries. Verified with `python -m py_compile src\grant_agent\mission_phase_inputs.py src\grant_agent\planner.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_inputs.py tests\test_mission_receipt_schemas.py -q` (`8 passed`).
  Files: `src/grant_agent/mission_phase_inputs.py`, `tests/test_mission_phase_inputs.py`

- [x] OP-015 Add one bounded repair loop driven by verifier output.
  Proof: Extended the phase runner so verifier `repair_needed` routes through one repair loop by default, records `repair_loop_count` and `maximum_repair_loops` on the MissionRun envelope, resets verifier for the post-repair attempt, and blocks truthfully when the repair loop limit is exhausted. Verified with `python -m py_compile src\grant_agent\mission_phase_runner.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_runner.py tests\test_mission_run_model.py -q` (`8 passed`).
  Files: `src/grant_agent/mission_phase_runner.py`, `tests/test_mission_phase_runner.py`

### Phase 3 - Night Mode Production Profile

- [x] OP-016 Replace safe-maintenance-only night mode with production night profile.
  Proof: Added a `night_mode` production profile contract that enables production mission execution, headless executor/verifier work, proof compaction, morning digest generation, and explicit deferral for browser/build/destructive work based on gateway/capacity/approval constraints. Updated `docs/NIGHT_MODE.md` so it no longer describes night mode as safe-maintenance-only. Verified with `python -m py_compile src\grant_agent\night_mode.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py -q` (`3 passed`).
  Files: `src/grant_agent/night_mode.py`, `docs/NIGHT_MODE.md`, `tests/test_night_mode.py`

- [x] OP-017 Add `NightReadinessReceipt`.
  Proof: Added `build_night_readiness_receipt` to produce a real `NightReadinessReceipt` with NAS worker, runtime auth, runtime availability, skills, workspace path, disk pressure, mission queue, notification, desktop gateway, and masked key checks. The receipt blocks truthfully when required checks fail. Verified with `python -m py_compile src\grant_agent\night_mode.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py tests\test_mission_receipt_schemas.py -q` (`8 passed`).
  Files: `src/grant_agent/night_mode.py`, `tests/test_night_mode.py`

- [x] OP-018 Add night queue policy: reconcile, repair, headless execution, headless verification, proof compaction, morning digest.
  Proof: Added `rank_night_queue` with production-night priority order for blocked reconciliation, repair, headless execution, headless verification, proof compaction, and morning digest generation. Capacity/approval-sensitive work is deferred through the production classifier and unknown work is held. Verified with `python -m py_compile src\grant_agent\night_mode.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py -q` (`7 passed`).
  Files: `src/grant_agent/night_mode.py`, `tests/test_night_mode.py`

- [x] OP-019 Add readiness failure messaging with receipt link.
  Proof: Added `build_readiness_failure_message` so blocked readiness produces a short action message with failure names, next action, mission id, and receipt path, while passed readiness skips messaging. Verified with `python -m py_compile src\grant_agent\night_mode.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py -q` (`9 passed`).
  Files: `src/grant_agent/night_mode.py`, `tests/test_night_mode.py`

- [x] OP-020 Add morning digest generation.
  Proof: Added structured morning digest generation and writer that produces `.agent_control/overnight/morning_digest_latest.json` and `.agent_control/overnight/morning_digest_latest.md` with completed items, blocked items, proof commands, changed files, NAS sync status, first unchecked item, and risks. Verified with `python -m py_compile src\grant_agent\night_mode.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py -q` (`10 passed`).
  Files: `src/grant_agent/night_mode.py`, `tests/test_night_mode.py`

### Phase 4 - Desktop Gateway

- [x] OP-021 Add desktop gateway heartbeat to NAS.
  Proof: Added `desktop_gateway` heartbeat recording that registers the PC as a `pc_gateway` accelerator in the cluster registry with browser/build/heavy verifier capabilities and writes heartbeat receipts under `.agent_control/desktop_gateway/heartbeats.jsonl`. Verified with `python -m py_compile src\grant_agent\desktop_gateway.py src\grant_agent\cluster.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_gateway.py tests\test_cluster_scheduler.py -q -k "desktop_gateway or host"` (`2 passed, 12 deselected`).
  Files: `src/grant_agent/desktop_gateway.py`, `tests/test_desktop_gateway.py`

- [x] OP-022 Route browser/build/heavy verifier jobs to PC gateway when online.
  Proof: Added gateway route decisions that send browser/build/heavy verifier jobs to an online `pc_gateway` host with matching capabilities, keep non-gateway jobs on the controller, and return a queued proof-gap decision when no capable PC gateway is online. Verified with `python -m py_compile src\grant_agent\desktop_gateway.py src\grant_agent\cluster.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_gateway.py -q` (`4 passed`).
  Files: `src/grant_agent/desktop_gateway.py`, `tests/test_desktop_gateway.py`

- [x] OP-023 Make gateway disappearance convert active gateway jobs into queued proof gaps, not fake failures.
  Proof: Added `reconcile_disappeared_gateway_jobs`, which scans active browser/build/heavy gateway jobs and converts jobs assigned to stale/missing PC gateways back to queued proof gaps with a `gateway.proof_gap_queued` event instead of marking them failed. Verified with `python -m py_compile src\grant_agent\desktop_gateway.py src\grant_agent\cluster.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_gateway.py -q` (`5 passed`).
  Files: `src/grant_agent/desktop_gateway.py`, `tests/test_desktop_gateway.py`

- [x] OP-024 Add gateway event streaming back to NAS.
  Proof: Added gateway event streaming via `.agent_control/desktop_gateway/events.jsonl` plus cluster event mirroring for job-scoped gateway events, with loader support for job filtering. Verified with `python -m py_compile src\grant_agent\desktop_gateway.py src\grant_agent\cluster.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_gateway.py -q` (`6 passed`).
  Files: `src/grant_agent/desktop_gateway.py`, `tests/test_desktop_gateway.py`

### Phase 5 - Runtime Wrapper

- [x] OP-025 Add external runtime wrapper abstraction for Hermes/OpenClaw/OpenCode/Codex.
  Proof: Added `runtime_wrapper` with `RuntimeWrapperSpec` for Hermes, OpenClaw, OpenCode, and Codex command metadata, cwd, env-key inventory without secret values, timeout, tail paths, and event stream path. Verified with `python -m py_compile src\grant_agent\runtime_wrapper.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_runtime_wrapper.py -q` (`2 passed`).
  Files: `src/grant_agent/runtime_wrapper.py`, `tests/test_runtime_wrapper.py`

- [x] OP-026 Track cwd, env status, process tree, TTL, heartbeat, stdout tail, stderr tail.
  Proof: Added `RuntimeWrapperState` with cwd, masked env status, process tree, TTL, heartbeat age, stdout tail path/content, and stderr tail path/content, with bounded tail reads. Verified with `python -m py_compile src\grant_agent\runtime_wrapper.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_runtime_wrapper.py -q` (`3 passed`).
  Files: `src/grant_agent/runtime_wrapper.py`, `tests/test_runtime_wrapper.py`

- [x] OP-027 Make runtime wrapper emit phase events and receipts.
  Proof: Added runtime wrapper phase event and execution receipt builders so wrapper output can report phase status and produce `ExecutionReceipt` evidence without marking missions complete. Verified with `python -m py_compile src\grant_agent\runtime_wrapper.py src\grant_agent\models.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_runtime_wrapper.py tests\test_mission_receipt_schemas.py -q` (`7 passed`).
  Files: `src/grant_agent/runtime_wrapper.py`, `tests/test_runtime_wrapper.py`

- [x] OP-028 Add replay support from recorded event stream and receipts.
  Proof: Added runtime wrapper replay loading from JSONL event streams and receipt JSON files, skipping corrupt rows and deriving latest status from receipts/events without inventing missing data. Verified with `python -m py_compile src\grant_agent\runtime_wrapper.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_runtime_wrapper.py -q` (`5 passed`).
  Files: `src/grant_agent/runtime_wrapper.py`, `tests/test_runtime_wrapper.py`

### Phase 6 - SkillBrief And Sub-Agent Receipts

- [x] OP-029 Add `SkillBrief` builder.
  Proof: Added `SkillBrief` and `SkillLibrary.build_skill_brief()` so Fluxio builds a bounded task-relevant skill brief from existing curated, user-installed, repo-specific, learned, usage, and feedback data without blindly loading full skill instructions. The brief carries selected skills, repo-specific skills, allowed tools, forbidden areas, examples, constraints, known failures, and prior successful recipes. Verified with `python -m py_compile src\grant_agent\models.py src\grant_agent\skill_library.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_skill_brief.py -q` (`2 passed`).
  Files: `src/grant_agent\models.py`, `src/grant_agent\skill_library.py`, `tests/test_skill_brief.py`

- [x] OP-030 Make planner select skills explicitly.
  Proof: Extended `build_docs_first_plan_receipt` to accept a `SkillBrief` and derive bounded `selected_skills` from its selected skill rows when no manual skill override is supplied, while recording the brief id/schema/count in planner inputs. Manual selected skills still override the brief. Verified with `python -m py_compile src\grant_agent\planner.py src\grant_agent\models.py src\grant_agent\skill_library.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_planner.py tests\test_skill_brief.py -q` (`7 passed`).
  Files: `src/grant_agent\planner.py`, `tests/test_planner.py`, `src/grant_agent\models.py`, `src/grant_agent\skill_library.py`, `tests/test_skill_brief.py`

- [x] OP-031 Make executor receive only selected skills.
  Proof: Added a SkillBrief-path executor phase-input contract test showing executor receives only selected skill ids from the plan receipt and does not receive the brief id, repo-specific skill rows, known-failure details, or other full brief/catalog context. Existing `build_executor_phase_input` already enforces this compact boundary. Verified with `python -m py_compile src\grant_agent\mission_phase_inputs.py src\grant_agent\planner.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_inputs.py tests\test_planner.py -q` (`11 passed`).
  Files: `tests/test_mission_phase_inputs.py`, `src/grant_agent\mission_phase_inputs.py`, `src/grant_agent\planner.py`

- [x] OP-032 Make verifier check whether selected skills were relevant.
  Proof: Added `check_selected_skill_relevance` so verifier-side code produces a receipt-style relevance check for the plan's selected skills against the original goal and optional SkillBrief context, passing relevant selections, flagging unrelated selections for review, and blocking empty skill selections. Verified with `python -m py_compile src\grant_agent\mission_phase_inputs.py src\grant_agent\planner.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_phase_inputs.py -q` (`9 passed`).
  Files: `src/grant_agent\mission_phase_inputs.py`, `tests/test_mission_phase_inputs.py`

- [x] OP-033 Add sub-agent receipt format for isolated research/review/diagnostics.
  Proof: Added `SubAgentReceipt` and `build_sub_agent_receipt` for bounded advisory receipts covering assignment, inputs, files inspected, findings, confidence, proof paths, and next recommendation. Roles/statuses are normalized, large fields are capped, and receipts remain advisory so they do not fake mission state. Verified with `python -m py_compile src\grant_agent\models.py src\grant_agent\sub_agent_receipts.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_sub_agent_receipts.py -q` (`3 passed`).
  Files: `src/grant_agent\models.py`, `src/grant_agent\sub_agent_receipts.py`, `tests/test_sub_agent_receipts.py`

### Phase 7 - Adaptive Verification

- [x] OP-034 Add verification ladder planner.
  Proof: Added `build_verification_ladder` to plan ordered verification receipt steps from changed files and capacity policy, including syntax/import, changed-file targeted, backend smoke, UI smoke, frontend build, and browser verification with explicit skip/gating reasons. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`4 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

- [x] OP-035 Implement syntax/import receipt.
  Proof: Added `build_syntax_import_receipt` to run a real `python -m py_compile` check against changed Python files, capture command/exit/stdout/stderr summaries, and truthfully report skipped non-Python files plus missing Python files. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`7 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

- [x] OP-036 Implement changed-file targeted check receipt.
  Proof: Added `build_changed_file_targeted_receipt` to run real `pytest` checks for changed test files, truthfully skip when no direct test target exists, and fail when listed changed test files are missing. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`10 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

- [x] OP-037 Implement backend command smoke receipt.
  Proof: Added `build_backend_command_smoke_receipt` to run explicitly supplied backend smoke commands, capture bounded command output, fail fast on the first command failure, and truthfully skip when no backend smoke command is provided. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`13 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

- [x] OP-038 Implement UI/button smoke receipt.
  Proof: Added `build_ui_button_smoke_receipt` to record bounded real UI interaction observations with proof paths, pass only when interactions pass, fail when any interaction fails, and skip truthfully when no browser/UI interaction proof was provided. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`16 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

- [x] OP-039 Gate full frontend build and browser verification behind capacity policy.
  Proof: Added `build_verification_capacity_policy` so full frontend build and browser verification are enabled only when PC gateway, time budget, and operator-presence constraints allow them; otherwise the verification ladder records capacity-gated skips instead of pretending heavy UI checks ran. Verified with `python -m py_compile src\grant_agent\verification_ladder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_verification_ladder.py -q` (`18 passed`).
  Files: `src/grant_agent\verification_ladder.py`, `tests/test_verification_ladder.py`

### Phase 8 - Flight Recorder And Debugger

- [x] OP-040 Add mission flight recorder.
  Proof: Added `MissionFlightRecorder` to append bounded flight-recorder JSONL events and write a snapshot containing last 200 events, current phase, runtime command, cwd, masked env status, process ids, lease id, heartbeat age, queue reason, stdout/stderr tails, changed files, verifier result, and next recovery action. Verified with `python -m py_compile src\grant_agent\flight_recorder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_flight_recorder.py -q` (`3 passed`).
  Files: `src/grant_agent\flight_recorder.py`, `tests/test_flight_recorder.py`

- [x] OP-041 Add debugger bundle command.
  Proof: Added `write_debugger_bundle` to create a diagnostic bundle manifest, copy explicitly provided evidence files, record missing evidence as gaps, and include bounded registry, process-tree, and queue-state snapshots without fabricating data. Verified with `python -m py_compile src\grant_agent\debugger_bundle.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_debugger_bundle.py -q` (`2 passed`).
  Files: `src/grant_agent\debugger_bundle.py`, `tests/test_debugger_bundle.py`

- [x] OP-042 Add "what failed / where / why / next action" diagnostic summary.
  Proof: Added `build_diagnostic_summary` to produce an evidence-backed diagnostic summary from flight-recorder snapshots, debugger bundles, and latest receipts, including what failed, where it failed, likely why, proof paths, and next action without fabricating a failure when evidence is absent. Verified with `python -m py_compile src\grant_agent\debugger_bundle.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_debugger_bundle.py -q` (`4 passed`).
  Files: `src/grant_agent\debugger_bundle.py`, `tests/test_debugger_bundle.py`

- [x] OP-043 Surface flight recorder in mission detail payload.
  Proof: Extended the mission-run read model in mission detail to surface a compact `flightRecorder` payload from the real flight-recorder snapshot when present, and an explicit `present: false` read model when absent, without mutating `missions.json`. Verified with `python -m py_compile src\grant_agent\mission_control.py src\grant_agent\flight_recorder.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_mission_control.py -q -k "mission_detail_exposes_legacy_mission_run_read_model_without_migration or mission_detail_read_model_surfaces_per_mission_receipts or mission_detail_surfaces_flight_recorder_snapshot"` (`3 passed, 159 deselected`).
  Files: `src/grant_agent\mission_control.py`, `tests/test_mission_control.py`, `src/grant_agent\flight_recorder.py`, `tests/test_flight_recorder.py`

### Phase 9 - UI Shell Integration

- [x] OP-044 Add current phase to mission shell center lane.
  Proof: Updated the Agent mission command center to derive the current phase from mission-run/flight-recorder data before falling back to legacy mission state, and render a compact `Current phase` line with source/value data attributes in the center lane. Verified with `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_ui_contract.py -q -k "agent_command_center_surfaces_current_phase_from_mission_run"` (`1 passed, 64 deselected`) and `npm run frontend:build` (Vite build passed; existing chunk-size warning only).
  Files: `web/src/neyvia/NeyviaShell.jsx`, `tests/test_desktop_ui_contract.py`

- [x] OP-045 Add focused task navigator.
  Proof: Added a focused task navigator to the Agent mission command center, deriving bounded task rows from mission-run receipts/tasks and mission state, with a follow-up action that carries the selected task back into the agent composer. Verified with `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_ui_contract.py -q -k "agent_command_center_has_focused_task_navigator or agent_command_center_has_proof_timeline_from_receipts or agent_command_center_has_capacity_and_proof_gap_rail or agent_command_center_has_morning_digest_view"` (`4 passed, 65 deselected`) and `npm run frontend:build` (passed; existing Vite chunk-size warning only).
  Files: `web/src/neyvia/NeyviaShell.jsx`, `tests/test_desktop_ui_contract.py`

- [x] OP-046 Add proof timeline based on receipts.
  Proof: Added a mission proof timeline in the Agent command center from `missionRun.receipts` / `receiptRefs`, showing bounded receipt phase/status/summary rows and an explicit empty state when no receipts are attached. Verified with `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_ui_contract.py -q -k "agent_command_center_has_focused_task_navigator or agent_command_center_has_proof_timeline_from_receipts or agent_command_center_has_capacity_and_proof_gap_rail or agent_command_center_has_morning_digest_view"` (`4 passed, 65 deselected`) and `npm run frontend:build` (passed; existing Vite chunk-size warning only).
  Files: `web/src/neyvia/NeyviaShell.jsx`, `tests/test_desktop_ui_contract.py`

- [x] OP-047 Add NAS/PC capacity and proof gaps to supervision rail.
  Proof: Added a compact Agent supervision rail that surfaces NAS cluster status, PC/flight-recorder heartbeat attachment, and selected-mission proof-gap count/detail without inventing capacity data. Verified with `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_ui_contract.py -q -k "agent_command_center_has_focused_task_navigator or agent_command_center_has_proof_timeline_from_receipts or agent_command_center_has_capacity_and_proof_gap_rail or agent_command_center_has_morning_digest_view"` (`4 passed, 65 deselected`) and `npm run frontend:build` (passed; existing Vite chunk-size warning only).
  Files: `web/src/neyvia/NeyviaShell.jsx`, `tests/test_desktop_ui_contract.py`

- [x] OP-048 Add morning digest view.
  Proof: Added a morning digest strip to the Agent command center using the live `visibleOvernightDigest` summary for completed, blocked, and proof-gap counts. Verified with `$env:PYTHONPATH='src'; python -m pytest tests\test_desktop_ui_contract.py -q -k "agent_command_center_has_focused_task_navigator or agent_command_center_has_proof_timeline_from_receipts or agent_command_center_has_capacity_and_proof_gap_rail or agent_command_center_has_morning_digest_view"` (`4 passed, 65 deselected`) and `npm run frontend:build` (passed; existing Vite chunk-size warning only).
  Files: `web/src/neyvia/NeyviaShell.jsx`, `tests/test_desktop_ui_contract.py`

### Phase 10 - Real Acceptance

- [x] OP-049 Start NAS backend and NAS worker on Example NAS.
  Proof: Synced 38 significant changed files to `nas-user@192.0.2.10:/volume1/Saclay/projects/vibe-coding-platform` over SSH legacy streaming because SFTP was unavailable, verified all remote SHA-256 hashes matched local hashes, then started the NAS backend and worker. Remote proof reported `backend-started 28177`, `worker-started 28180`, `alive .agent_control/overnight/nas_backend.pid 28177`, and `alive .agent_control/overnight/nas_worker.pid 28180`. Receipt: `.agent_control/overnight/op049_nas_start_receipt.json`.
  Files: `.agent_control/overnight/op049_nas_start_receipt.json`, `docs/OVERNIGHT_PRODUCTION_OPERATOR_PLAN.md`

- [x] OP-050 Run mission 2 through NAS night profile.
  Proof: Ran mission 2 (`mission_2`, Account watchdog cleanup) through the NAS production night profile on Example NAS. The profile allowed the work kind, but the real readiness receipt blocked execution because `runtime_auth_available` was false in the NAS worker environment, so no fake-running state was introduced. Remote receipt: `/volume1/Saclay/projects/vibe-coding-platform/.agent_control/overnight/op-050_mission_2_night_profile_receipt.json`; local summary: `.agent_control/overnight/op-050_mission_2_night_profile_summary.json`.
  Files: `.agent_control/overnight/op-050_mission_2_night_profile_summary.json`, `.agent_control/overnight/op050_052_nas_night_profile_stdout.json`, `.agent_control/overnight/op050_052_nas_night_profile_stderr.txt`

- [x] OP-051 Run mission 3 through NAS night profile.
  Proof: Ran mission 3 (`mission_3`, HAPS/AUV simulator upgrade) through the NAS production night profile on Example NAS. The profile deferred browser verification because the PC gateway was not online for accelerator work, so the receipt records a truthful deferred state and no fake-running mission state. Remote receipt: `/volume1/Saclay/projects/vibe-coding-platform/.agent_control/overnight/op-051_mission_3_night_profile_receipt.json`; local summary: `.agent_control/overnight/op-051_mission_3_night_profile_summary.json`.
  Files: `.agent_control/overnight/op-051_mission_3_night_profile_summary.json`, `.agent_control/overnight/op050_052_nas_night_profile_stdout.json`, `.agent_control/overnight/op050_052_nas_night_profile_stderr.txt`

- [x] OP-052 Run mission 4 through NAS night profile.
  Proof: Ran mission 4 (`mission_4`, JBHEAVEN/T3MP3ST research) through the NAS production night profile on Example NAS. The profile allowed the work kind, but the real readiness receipt blocked execution because `runtime_auth_available` was false in the NAS worker environment, so no fake-running state was introduced. Remote receipt: `/volume1/Saclay/projects/vibe-coding-platform/.agent_control/overnight/op-052_mission_4_night_profile_receipt.json`; local summary: `.agent_control/overnight/op-052_mission_4_night_profile_summary.json`.
  Files: `.agent_control/overnight/op-052_mission_4_night_profile_summary.json`, `.agent_control/overnight/op050_052_nas_night_profile_stdout.json`, `.agent_control/overnight/op050_052_nas_night_profile_stderr.txt`

- [x] OP-053 Prove process reaper dry-run is clean after missions 2, 3, and 4.
  Proof: After the NAS night-profile receipts for missions 2, 3, and 4, ran `ClusterRegistry.process_reaper(dry_run=True, stale_seconds=300, limit=100)` on Example NAS. The receipt returned schema `fluxio.process_reaper.v1`, `dryRun: true`, `candidateCount: 0`, `candidates: []`, and `status: clear`. Local proof: `.agent_control/overnight/op053_process_reaper_dry_run_stdout.json`.
  Files: `.agent_control/overnight/op053_process_reaper_dry_run_stdout.json`, `.agent_control/overnight/op053_process_reaper_dry_run_stderr.txt`

- [x] OP-054 Prove morning digest shows completed, blocked, and proof-gap states truthfully.
  Proof: Extended the morning digest contract with explicit `completedCount`, `blockedCount`, `proofGapCount`, and `proofGaps` fields, plus a markdown Proof Gaps section. Generated `.agent_control/overnight/morning_digest_latest.json` and `.agent_control/overnight/morning_digest_latest.md` showing 6 completed rows, 2 blocked rows, and 1 proof-gap row from this run. Verified with `python -m py_compile src\grant_agent\night_mode.py` and `$env:PYTHONPATH='src'; python -m pytest tests\test_night_mode.py -q` (`10 passed`).
  Files: `src/grant_agent\night_mode.py`, `tests/test_night_mode.py`, `.agent_control/overnight/morning_digest_latest.json`, `.agent_control/overnight/morning_digest_latest.md`

## First Unchecked Step

At the time this file was created, the first unchecked step is:

```text
none
```

Future automation should recompute this from the checkboxes above instead of trusting this note.

## Operating Instructions For Future Agents

Before implementing:

1. Read this file.
2. Run `rg -n "^- \[[ x]\] OP-" docs/OVERNIGHT_PRODUCTION_OPERATOR_PLAN.md`.
3. Identify the first unchecked step.
4. Inspect current code before editing.
5. Implement only what is needed for that step.
6. Add proof.
7. Mark the step checked.
8. If a better step is required first, add it immediately before the current step and explain why.

Do not skip directly to UI polish.

Do not start by adding more dashboards.

Do not mark a step complete without a receipt, command output, or focused test.

## Current Definition Of Done

This architecture is done when:

- NAS can run overnight without PC awake.
- PC accelerates automatically when awake.
- missions 2, 3, and 4 finish or produce honest blocked proof.
- no fake-running missions remain.
- every phase has receipts.
- morning report tells what happened.
- process reaper dry-run is clean.
- user can trust the system before sleeping.

## Notes

The full broad test suite is not the proof target for this architecture.

The proof target is mission-level completion with durable receipts.

Use focused contract tests for scheduler, leases, receipts, reaper, and phase transitions.

Use functional proof for buttons, backend commands, runtime processes, and mission completion.

Publication note: local account paths and network identifiers in this document are neutral examples.
