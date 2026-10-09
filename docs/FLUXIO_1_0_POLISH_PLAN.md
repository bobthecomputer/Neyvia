# Fluxio 1.0 Polish Plan

This document is the operator-quality companion to `docs/FLUXIO_1_0_RELEASE.md`.

It exists to keep the `1.0` push focused on one question:

- does Fluxio feel trustworthy, accessible, and worth returning to while doing real work?

The answer must be yes for multiple skill levels, not just for command-line-native users.

## North Star

`Fluxio 1.0` is not just "agents running for hours."

It is:

- a system that can hold an objective for many hours
- reset or compress context without losing the mission
- bring back the right context, skill, and proof
- learn from failures and promote reusable patterns
- remain understandable and controllable to a human operator throughout

That means `1.0` has two equal halves:

- technical agency quality
- human operator quality

If the internals are strong but the felt experience is bad, `1.0` is still incomplete.

## Premium Polish Checklist

This is the tighter `1.0 premium polish` checklist mapped onto the actual implementation surfaces.

### Today: ship the premium supervision shell

- `web/src/neyvia/NeyviaApp.tsx`
  - keep one focused task and one dominant next-action surface in the center lane
  - make proof stronger than narration with a "what changed since your last look" surface
  - make the runtime lane explain itself: why this runtime now, continuity truth, execution location, and handoff history
  - keep the right rail strict: review boundaries, guardrails, runtime health, leverage, escalation
  - make the proof dialog useful for fast review instead of a raw diff dump
- `web/src/neyvia/neyviaBridge.ts`
  - upgrade the generated thread proof text so it includes runtime lane, continuity, execution location, and handoff rationale
  - upgrade diff summaries so review proof survives restarts and operator returns
  - keep proof copy grounded in the shared snapshot, not UI-only assumptions
- `desktop-ui/missionControlModel.js`
  - expose explicit orchestration primitives for the shell instead of generic cards
  - surface proof-review state, runtime rationale, execution-location truth, and handoff history
  - keep profile-aware density and wording intact while reducing clutter

### Next: finish the shared continuity and proof contract

- `src/grant_agent/mission_control.py`
  - keep one authoritative continuity state, pause reason, runtime lane, elapsed time, and remaining time path
  - expose approval history count, delegated-lane state, and runtime-switch rationale clearly enough for the UI to explain them without guesswork
  - add explicit execution-target truth once local vs worktree vs NAS support becomes a real operator choice
- `src/grant_agent/runtime_supervisor.py`
  - preserve delegated approval history, latest structured events, execution root, and restart-safe lane status
  - make completed or resumed delegated sessions easy to prove from the shared snapshot
- `src/grant_agent/models.py`
  - keep typed fields aligned with the supervision shell
  - when execution-target work lands, add explicit fields for execution target, storage mode, and host locality instead of inferring from path strings forever

### Follow-up: execution-target leverage informed by the sibling Cowork project

- `C:/Users/example/projects/Cowork/launcher-server.js`
  - reference the existing WSL bridge and "local machine, not remote host" runtime note when designing Fluxio execution-location truth
  - reuse the idea of a stable bridge path and explicit workspace-root explanation, not the exact launcher UI
- `C:/Users/example/projects/Cowork/synology_fast_ui/index.html`
- `C:/Users/example/projects/Cowork/synology_fast_ui/app.js`
- `C:/Users/example/projects/Cowork/synology_fast_ui/styles.css`
  - use these as reference material for a future explicit local-vs-NAS execution target, sync health, and unattended-run storage choice
  - do not pull Synology management into the main Fluxio shell until the core local-first supervision loop already feels premium

## Core Product Standard

Fluxio should work for four user levels on the same product surface:

- non-technical
- semi-technical
- technical builder
- expert operator

Personalization is not a settings afterthought.
It must materially change the way setup, approvals, language, visibility, and recovery feel.

## Required Human-Feel Audit States

Every meaningful UI or workbench pass must be reviewed against these states:

- first run
- setup blocked
- mission launch
- approval wait
- resumed mission
- verification failure
- long-run mission return
- skill promotion

Use the human-centered audit skill at:

- `C:/Users/example/.codex/skills/fluxio-human-feel-audit`

The audit output should become a ranked fix list. Resolve the top issues before adding new surface area.

## Profile Contract

Profile choice must materially change the product surface:

- `Beginner`
  - more explanation
  - fewer visible controls by default
  - stronger safety wording
  - guided setup and repair language
- `Builder`
  - compact but plain-language default
  - visible proof and verification
  - practical next actions
- `Advanced`
  - denser truth
  - lower narration
  - more direct runtime and Git detail

If profile selection only changes metadata or small labels, the work is not done.

## Plan Interaction Contract

The workbench must show one explicit plan-interaction lane that answers four questions:

- what Fluxio knows
- what assumption it is making
- what it needs to ask
- what the next operator action is

The system should not feel mute, robotic, or trapped in rigid loop execution.
The operator should feel that Fluxio:

- understands uncertainty
- notices when it should check assumptions
- can ask concise questions without collapsing the mission
- can continue confidently when it has enough context

## State Design Contract

Remove remaining filler or admin-panel feeling by replacing dead sections with real operator states:

- empty
- blocked
- resumed
- failed
- post-mission

The center of gravity should stay on:

- what is running
- what is blocked
- what needs approval
- what changed
- what should happen next

## Fixed 1.0 Sequence

The sequence is fixed and should stay aligned with the release definition.

### Phase 1: Reliability Contract And Launch Safety

- Close launch and restart reliability gaps first.
- Treat `npm run verify:desktop` as the canonical desktop validation command.
- Make shared mission snapshot truth authoritative for elapsed time, remaining time, pause reason, budget status, and runtime lane.
- Keep Hermes and `uv` as hard blockers in setup logic, acceptance tests, and user-facing copy.

### Phase 2: Human-Quality Workbench And Personalization

- Run the human-feel audit across the required states.
- Convert the audit into a ranked fix list and resolve the top issues before widening scope.
- Make profile choice materially change the UI.
- Add the explicit plan-interaction lane.
- Remove remaining filler and dead states.

### Phase 3: Skill Studio Completion

- Finish Skill Studio as one end-to-end workflow: create from template, import, edit, test, enable, disable, archive, promote, and reuse.
- Back visible skill actions with persisted library state.
- Keep learned skills distinct from reviewed reusable skills.
- Reuse prior successful skills automatically in mission and workflow suggestions.

### Phase 4: Service Management Completion

- Finish Service Management as one detect, install, verify, repair, and manage loop shared between setup and `Builder View`.
- Keep four categories visible and distinct:
  - local services
  - MCP/tool servers
  - runtimes
  - connected-app bridges
- Support safe install and repair for Fluxio-managed items with post-action verification.
- Show truthful detection and health details for externally managed items without fake repair flows.

### Phase 5: Workflow Studio And Agency Hardening

- Keep Workflow Studio narrow: save-run, replay, and reviewed recipe composition only.
- Harden the mission loop so Fluxio continues when context is sufficient, asks when assumptions are high-impact, replans when blocked, and only creates or promotes a skill when repeated value is evident.
- Preserve context summaries across long runs and restarts.

### Phase 6: 1.0 Validation Cycle

- Validate on the supported Windows desktop + WSL2 path only.
- Require proof capture for first-run blocked setup, service repair, approval wait, verification failure, resumed long-run mission, and skill test or promotion.
- Require a real proving mission on OpenClaw and a real delegated mission on Hermes.

### Phase 7: 1.1 Leverage Release

- Add leverage, not breadth.
- Focus on reviewed workflow packs, stronger automatic skill reuse, service drift detection, and operator-value trust scoring.
- Do not introduce cloud sync, inbox or thread products, container abstractions, or a heavyweight workflow builder.

## Human-Feel Failure Conditions

`1.0` should fail polish review if any of these are still true:

- a non-technical user still feels stranded on setup
- a builder still feels faster in competing tools for ordinary work
- the UI still feels worse than the underlying capability
- profile selection does not meaningfully change the felt experience
- long autonomous runs still feel vague, fragile, or hard to trust
- the user does not feel free to build

## Review Method

Run the audit after each major UI or workbench pass.
Fail the `1.0` validation cycle if any audit concludes that:

- setup strands beginners
- profile choice feels cosmetic
- the workbench still feels worse than the underlying capability

## Not For 1.0

Do not let these distract the polish push:

- broad connected-app expansion
- heavyweight workflow builder
- cloud team features
- marketplace or ecosystem rollout
- generic multi-agent spectacle features

The correct `1.0` move is simple:

- finish reliability
- finish the operator experience
- make Fluxio feel strong enough that people want to come back to it

Publication note: local account paths and network identifiers in this document are neutral examples.
