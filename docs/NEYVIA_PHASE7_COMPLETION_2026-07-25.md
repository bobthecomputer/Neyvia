# Neyvia Phase 7 completion

Status: complete for every pre-provider-approval item.

The first real Thunder Compute connection and paid action remain intentionally
disabled. They are the final operator-led step after implementation review.

## What became usable

- Durable mission records now expose the goal, plan, current and last completed
  step, facts, artifacts, attempts, checkpoint, pending input, known failure,
  and safest next action.
- Transient worker and cluster failures resume from the durable checkpoint with
  bounded exponential backoff. Authentication, permission, approval, and cost
  failures wait for operator input. Permanent or exhausted failures remain
  visible and contained.
- Coordinator-loop failures write a durable receipt instead of disappearing.
- Research can discover independent web alternatives, continue after a source
  failure, capture evidence, filter it by requested/excluded terms, and return
  ranked results without claiming that an opportunity is legitimate before
  provider/operator review.
- A normal file transfer executes exactly two checks: destination existence and
  one size/hash integrity check. It records that no unrelated checks ran.
- Thunder Compute has an official-MCP-shaped, explicitly simulated adapter with
  instance, project, repository, notebook, job, log, metric, checkpoint,
  artifact, metering, restart/idempotency, failure, and idle-release evidence.
- GPU policy is configurable for concurrency, estimated cost, duration, and
  retain/stop/snapshot-delete behavior. Paid execution remains false.
- The calm mission shell shows current action, recovery route, retry state,
  checkpoint evidence, blockers, proof, and GPU policy only when relevant.
- User-scoped versioned preferences cover progress cadence, notification
  importance, autonomy, approval threshold, verification depth, GPU limits,
  motion intensity, transparency, and reduced motion.

## Five acceptance journeys

1. Restart/resume: the simulated broker was rebuilt and the repeated launch was
   deduplicated.
2. Research fallback: one supplied source timed out and an independent
   discovered source completed the result.
3. File transfer: the receipt contained exactly two successful proportional
   checks and no unrelated test cascade.
4. GPU/ASR: project context, approval boundary, launch, restart, checkpoint,
   logs, metrics, artifacts, meter data, and snapshot/delete idle release were
   confirmed in a few milliseconds with no network, credential, spend, or GPU.
5. Failure containment: a provider timeout retried once, exhausted its bounded
   budget, became a visible failed mission state, and the coordinator error
   produced a durable receipt.

Focused automated result: 61 passed.

User-like browser result: the app opened through the local authenticated route,
Continuity settings were changed and survived reload, the runtime page clearly
identified simulated/no-spend mode, the journey passed, and idle-policy proof
was visible.

Production frontend build: passed. The existing large-chunk warning remains;
there was no build failure.

## Evidence

- Browser screenshot:
  `proof/phase7/continuity-settings.png`
- Screenshot SHA-256:
  `A00AD2FC6B40D1A01235CDA4BDE6CD26A7532854BFD0050AB9AFDB6170142D0B`
- Latest simulated Thunder receipt:
  `.agent_control/mission_artifacts/thunder_compute/simulated-asr-a67ad3d24e9a.json`
- Thunder receipt SHA-256:
  `55DE2C2043CED7EAD17B315CBE2190F1EF4ADF220DE0CCF8F524FFF50462200D`

## Defects found and corrected

- First-attempt cluster job IDs briefly lost backward compatibility.
- HTTP 401/403 errors were initially at risk of being grouped with transient
  URL errors.
- A repeated simulated journey reused a released fixture and could fail.
- The first Thunder card theme used an inherited panel variable that rendered
  as a washed-out white block in the dark shell.
- The first UI script targeted the public landing page instead of `/control`.

## Honest limitations and final operator step

- The official Thunder Compute OAuth MCP is not connected in this local
  acceptance run.
- No real provider state, real GPU, real ASR progress, or paid result is claimed.
- Python Torch and Python Playwright are not installed in the selected `.venv`;
  the focused Phase 7 browser journey used the installed Node Playwright runtime.
- The repository was already broadly dirty, so no commit or push was created.
  Base HEAD during this report was
  `46b07c26ad3be41db5fbf2a1f06fd9d114fa7726` on `master`.
- Phase 7 pre-approval scope is 100% complete. Real Thunder/ASR connected
  acceptance remains 0% until the operator connects OAuth and authorizes one
  bounded job.

## Opus review handoff

Opus should review the completed interfaces without modifying Phase 7 runtime
internals:

1. Confirm the shell consumes `neyvia.mission-continuity-record.v1` without
   overstating provider success.
2. Confirm Milestone 8 module namespaces and preference isolation cannot replace
   or reset the new core continuity/GPU preferences.
3. Confirm marketplace effects respect `motionIntensity`,
   `visualTransparency`, and `reduceMotion`.
4. Confirm the first real provider setup remains an explicit final operator
   action.

No Opus approval is claimed by this document.

## NAS verification

- Remote directory:
  `/volume1/Saclay/projects/syntelos/work-in-progress/20260725-2104-neyvia-phase7-complete/`
- Archive:
  `neyvia-phase7-complete-20260725-2104.zip`
- Uploaded bytes: `1226318`
- First verified archive SHA-256:
  `D440E452623F0EACA896DE321EE1819A1639527CEB9E28708FCCC223D2B9D6F5`

The archive was uploaded with legacy SCP mode for Synology compatibility and
verified remotely with `sha256sum`. A final archive refresh may have a different
digest when this NAS verification paragraph is included; the final digest is
reported in `proof/phase7/acceptance-receipt.json` and the task handoff.
