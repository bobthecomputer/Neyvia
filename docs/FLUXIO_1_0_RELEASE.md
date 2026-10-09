# Fluxio 1.0 Release Definition

`Fluxio 1.0` is the reliable local-first stop point for the product.

The purpose of `1.0` is not breadth. The purpose is:

- Fluxio is trustworthy on one real path: Windows desktop app + WSL2-backed runtimes
- the operator can launch, supervise, recover, and finish long delegated missions without state drift
- setup, proof, skill reuse, and service truth are strong enough that Fluxio can help build later versions of itself

If that is not true on the supported local-first path, it is not `1.0`.

## 1.0 Product Promise

Fluxio `1.0` is a desktop-first autonomous coding workbench that lets a user:

- run local-first missions from the Windows desktop path with WSL2 as the supported runtime substrate
- choose between OpenClaw and Hermes behind one shared control-room snapshot
- supervise one mission truth across `Agent View` and `Builder View`
- recover cleanly from restart during delegated approvals, delegated runtime activity, and long unattended runs
- understand real proof, verification, pause reasons, elapsed time, and remaining time without reading logs first
- manage setup, skills, workflows, and connected-app bridges from the same workbench without a second product shell

## 1.0 Reliability Contract

Fluxio `1.0` is explicitly local-first and Windows-first:

- supported operator path: Windows desktop app
- supported runtime substrate: WSL2
- required setup contract: Node, Python, `uv`, OpenClaw, Hermes, Tauri prerequisites, Telegram readiness, and one first guided mission
- hard blockers for `1.0`: `uv` missing or Hermes missing/unusable on the validation machine
- canonical desktop validation command: `npm run verify:desktop`
- required use of the canonical validation command: any setup, mission-truth, or desktop workbench change must pass `npm run verify:desktop` before the work is treated as ready

Fluxio `1.0` does not attempt a general environment abstraction layer.

- VM and containerized environment management are deferred beyond brief docs-only escape hatches
- there is no new supervisory mode, no second mission-state model, and no separate thread or inbox product

## 1.0 Must-Haves

### Core mission loop

- Mission creation from the desktop UI works end to end.
- Fluxio planner loop supports plan, execute, verify, and replan instead of one-shot planning.
- One mission can continue across restarts with state, plan revisions, derived tasks, and proof intact.
- One active mission per workspace remains the default, with truthful queueing and collision avoidance.
- The current dual-runtime desktop path is accepted and usable through the shared workbench.

### Delegated runtime continuity

- OpenClaw and Hermes are both selectable runtimes.
- Delegated runtime lanes have authoritative lifecycle states:
  - `queued`
  - `launching`
  - `running`
  - `waiting_for_approval`
  - `completed`
  - `failed`
  - `stopped`
- Delegated approvals survive restart and resume cleanly.
- Restart during delegated runtime activity keeps continuity, proof, and pause state truthful.
- Long-run missions show budget, elapsed time, remaining time, and pause reasons in operator language.
- Elapsed time, remaining time, pause reason, budget status, and current runtime lane all come from one shared mission snapshot path.

### Workbench truth and accessibility

- The shared control-room snapshot remains the only mission truth model.
- `Agent View` keeps current phase, approval state, continuity, proof, time budget, and next operator action in the center.
- `Builder View` keeps Git truth, action history, verification, runtime detail, service health, connected-app detail, and skill/workflow management visible against the same mission.
- The workbench includes one explicit plan-interaction lane that shows:
  - what Fluxio knows
  - what assumption it is making
  - what it needs to ask
  - what the next operator action is
- Profile choice materially changes the UI:
  - `Beginner`: more explanation, fewer visible controls by default, stronger safety wording, guided setup and repair language
  - `Builder`: compact but plain-language default, visible proof and verification, practical next actions
  - `Advanced`: denser truth, lower narration, more direct runtime and Git detail
- Filler sections are replaced with explicit first-run, blocked, resumed, failed, and post-mission states.
- Local and delegated actions remain visually distinguishable.

### Setup and Service Management

- Setup is installer-grade, plain-language, and local-first.
- WSL2, Node, Python, `uv`, OpenClaw, Hermes, Tauri prerequisites, Telegram readiness, and first guided mission are all visible in the canonical setup flow.
- `uv` and Hermes are hard blockers.
- Tutorial and setup copy must not imply the machine is ready while `uv` or Hermes is missing or unusable.
- Service Management is a first-class detect/install/verify/repair/manage loop, not a recommendation list.
- Setup and `Builder View` share one service truth path instead of duplicating logic.
- Four service categories stay visible and distinct:
  - local services
  - MCP/tool servers
  - runtimes
  - connected-app bridges
- Fluxio-managed services support safe install or repair actions followed by post-action verification before they can be marked healthy.
- Externally managed services show detection, version, install source, health, and verification truth without fake in-product repair flows.
- Setup and workspace payloads expose:
  - `serviceCategory`
  - `installSource`
  - `currentHealthStatus`
  - `lastVerificationResult`
  - `lastRepairAction`
  - `managementMode`
  - `version`
  - available actions for `install`, `repair`, and `verify` when appropriate

### Skill Studio

- Skill Studio is a first-class create, reuse, and manage loop, not a catalog-only surface.
- Every visible skill action is backed by persisted library state rather than preview-only UI.
- Creation captures the skill's human name, when-to-use description, project or personal scope, optional starter workflow, and a human creation note.
- A successful creation writes a validated `SKILL.md` plus `agents/openai.yaml`, refuses to overwrite an existing folder, and begins visible evolution history with an append-only revision-zero receipt.
- A failed creation leaves no incomplete skill package behind.
- Operators can:
  - create a skill from a template
  - import an existing skill
  - edit metadata, prompt hint, permissions, tags, and status
  - test a skill against a sample task
  - enable, disable, or archive a skill
  - promote a learned skill into a reviewed reusable skill
  - reuse recent and successful skills from prior missions without re-authoring
- Learned skills remain distinct from reviewed reusable skills, with promotion as the bridge.
- Successful prior skills are reused automatically in mission and workflow suggestions without forcing re-authoring.
- Skill evolution is visible and reviewable rather than implied:
  - every changed `SKILL.md` save validates required frontmatter and instructions
  - every reviewed version creates a byte-preserving backup, before/after hashes, a human change note, and an append-only evolution receipt
  - unchanged content does not manufacture a new revision
  - project-skill receipts stay with the project, while personal-skill receipts travel with the personal Codex library across workspaces
  - the selected skill shows use count, helped closeouts, clean verification slices, operator-value samples, recent versions, repair events, and the next evidence needed
  - usage alone never raises trust; clean verification, operator value, and human review remain required
- Skill-library payloads expose:
  - `editableStatus`
  - `testStatus`
  - `promotionState`
  - `lastUsedAt`
  - `lastHelpedAt`
  - `originType`
  - `evolutionSummary`
  - action affordances for `test`, `enable`, `disable`, `archive`, `promote`, and `reuse`

### Workflow Studio and agency hardening

- Workflow Studio stays narrow for `1.0`.
- It supports save-run, replay, and reviewed recipe composition only.
- Workflows are reviewed combinations of mission defaults, runtime choice, managed skills, managed services, and verification defaults.
- Workflow Studio does not become a heavyweight visual workflow builder or a separate execution model.
- The mission loop is hardened so Fluxio:
  - continues when enough context exists
  - asks when assumptions are high-impact
  - replans when blocked or verification changes the path
  - creates or promotes a skill only when repeated value is evident
  - preserves context summaries across long runs and restarts
- One active mission per workspace remains the default, with truthful queue and collision state.

### Bridge Lab

- Bridge Lab manifest and grant scope remain unchanged for `1.0`.
- `OratioViva` is a real reference integration.
- Storage and cloud bridges are the active external reference integrations.
- `Solantir` remains deferred.

### Accessibility and iteration

- Beginner wording remains intact.
- Reduced-motion support works.
- The desktop frontend keeps HMR in development.
- Fixture-backed review mode remains part of the product workflow.

## Fixed Implementation Order

The implementation order is fixed. `1.0` is not done by spreading effort evenly across all surfaces.

### Phase 1: Reliability Contract And Launch Safety

- Close launch and restart reliability gaps first.
- Treat `npm run verify:desktop` as the canonical desktop validation command and require it for setup, mission-truth, and desktop workbench changes.
- Add desktop smoke coverage for:
  - first-run setup
  - setup repair
  - launch with a proving mission
  - `Agent View` and `Builder View` switching
  - approval wait
  - resumed mission
  - long-run mission return
- Finish restart-safe continuity for delegated approvals and delegated runtime activity so the shared snapshot stays truthful after app restart.
- Keep Hermes and `uv` as hard blockers in setup logic, acceptance tests, and user-facing copy.

### Phase 2: Human-Quality Workbench And Personalization

- Run the human-feel audit against:
  - first run
  - setup blocked
  - mission launch
  - approval wait
  - resumed mission
  - verification failure
  - long-run mission return
  - skill promotion
- Turn the audit into a ranked fix list and resolve the top issues before adding new surface area.
- Make profile choice materially change the UI and copy for `Beginner`, `Builder`, and `Advanced`.
- Add the explicit plan-interaction lane to the workbench.
- Remove remaining filler and admin-panel feeling by replacing dead sections with explicit empty, blocked, resumed, failed, and post-mission states.

### Phase 3: Skill Studio Completion

- Finish Skill Studio as one end-to-end workflow: create from template, import, edit, test, enable, disable, archive, promote, and reuse.
- Back every visible skill action with persisted library state.
- Keep learned skills separate from reviewed reusable skills, with promotion as the bridge.
- Reuse prior successful skills automatically in mission and workflow suggestions.
- Make improvement cumulative and inspectable through validated, versioned saves and a selected-skill evolution history; never infer trust from repetition alone.

### Phase 4: Service Management Completion

- Finish Service Management as one detect, install, verify, repair, and manage loop shared between setup and `Builder View`.
- Keep local services, MCP/tool servers, runtimes, and connected-app bridges visible as distinct categories.
- Support safe install and repair for Fluxio-managed items with post-action verification.
- Show truthful detection and verification data for externally managed items without fake in-product repair.

### Phase 5: Workflow Studio And Agency Hardening

- Keep Workflow Studio narrow: save-run, replay, and reviewed recipe composition only.
- Represent workflows as reviewed combinations of mission defaults, runtime choice, managed skills, managed services, and verification defaults.
- Harden the agency loop around the mission model rather than introducing a separate execution engine.
- Preserve context summaries and queue truth across long runs and restarts.

### Phase 6: 1.0 Validation Cycle

- Validate on the supported Windows desktop + WSL2 path only.
- Require proof capture for first-run blocked setup, service repair, approval wait, verification failure, resumed long-run mission, and skill test or promotion.
- Require a real proving mission on OpenClaw and a real delegated mission on Hermes.
- Do not call `1.0` done until Skill Studio, Service Management, restart continuity, proof, and time-budget truth are complete together.

### Phase 7: 1.1 Leverage Release

- Move into a narrow `1.1` leverage release only after `1.0` truth is validated.
- Add reviewed workflow packs for the highest-value domains already supported by the product.
- Add stronger automatic skill reuse based on mission type, repo type, and recent success.
- Add service drift detection and "repair before run" suggestions.
- Add trust scoring focused on operator value: proof quality, false-success detection, and "Fluxio should have asked sooner" review.
- Keep `1.1` additive on top of the `1.0` truth model.

## 1.0 Explicit Non-Goals

These are allowed to remain incomplete in `1.0`:

- VM or container environment abstraction beyond short docs-only guidance
- a heavyweight visual workflow builder
- a separate supervisory shell, thread system, or inbox product
- a full public connected-app ecosystem rollout
- unrestricted arbitrary app orchestration
- cloud sync, multi-user team features, or full mobile product scope

## Release Blockers

Any of these block `1.0`:

- desktop dual-runtime acceptance from the supported local-first path is still unreliable
- delegated approvals do not recover correctly across restart
- delegated runtime activity does not recover correctly across restart
- mission proof is vague, misleading, or split across surfaces
- long-run missions still hide budget truth or pause reasons
- setup leaves the operator stuck on missing `uv`, missing Hermes, or WSL2 ambiguity
- setup or tutorial copy implies readiness while `uv` or Hermes is still missing or unusable
- Skill Studio remains catalog-only or preview-only
- Service Management remains recommendation-only
- the workbench still behaves like scattered admin panels instead of one coherent operator surface

## 1.0 Validation Gates

Fluxio is ready for a `1.0` validation cycle only when all of these are true:

- `python -m pytest tests -q` passes
- `npm run frontend:build` passes
- `npm run tauri build -- --debug` passes
- `npm run verify:desktop` passes and remains the canonical desktop gate
- desktop acceptance coverage exists for:
  - first run on a machine missing `uv`
  - first run on a machine missing Hermes
  - setup repair followed by verify
  - `Agent View` and `Builder View` switch with state intact
  - approval wait across restart
  - delegated runtime activity across restart
  - long-run mission return with truthful budget and pause reason
- workflow acceptance coverage exists for:
  - create, test, enable, disable, archive, and reuse a user-authored skill
  - promote one learned skill into a reviewed reusable skill
  - detect, install, and verify one runtime and one MCP/tool server
  - save and replay one reviewed workflow recipe using managed skills and services
- setup on a machine missing `uv` fails clearly and guides recovery
- setup on a machine missing Hermes fails clearly and guides recovery
- switching between `Agent View` and `Builder View` preserves mission, skill, and service context
- restart during delegated approval wait recovers correctly
- restart during delegated runtime activity recovers correctly
- a long-run mission shows truthful budget, elapsed time, remaining time, and pause reason
- a real proving mission runs on OpenClaw
- a real delegated mission runs on Hermes
- Hermes is installed and usable on the validation machine
- `uv` is installed and usable on the validation machine

## Human-Quality Review Gates

The `1.0` validation cycle fails if any human-feel audit concludes that:

- setup still strands beginners
- profile choice still feels cosmetic
- the workbench still feels worse than the underlying capability

The human-feel audit must be rerun after each major UI or workbench pass.

## Operator-Proof Capture

Operator-proof capture must exist for:

- first-run blocked setup
- service repair
- approval wait
- verification failure
- resumed long-run mission
- skill test and promotion flow

## 1.1 Leverage Release Boundary

`1.1` should multiply the `1.0` foundation rather than widen the scope.

`1.1` is allowed to add:

- reviewed workflow packs for already-supported domains
- stronger automatic skill reuse
- service drift detection and repair-before-run suggestions
- trust scoring around proof quality, false-success detection, and late-question review

`1.1` must not add:

- cloud sync
- an inbox or thread product
- container abstractions
- a heavyweight workflow builder

## Definition Of Done

We call it `Fluxio 1.0` when:

- the supported Windows + WSL2 local-first path is reliable enough for daily operator use
- `npm run verify:desktop` is the accepted validation contract for setup, mission-truth, and desktop workbench work
- the workbench feels coherent, truthful, personalized, and recoverable during real autonomous runs
- Skill Studio and Service Management are real operator workflows instead of placeholders
- restart continuity, proof, and time-budget truth are complete together
- the remaining gaps are post-`1.0` leverage work, not missing foundations
