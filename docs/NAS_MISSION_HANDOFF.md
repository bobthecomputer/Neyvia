# NAS mission handoff

Architecture source of truth: [Fluxio Overnight Production Operator Plan](OVERNIGHT_PRODUCTION_OPERATOR_PLAN.md).

This note is for continuing Neyvia Control work from another computer.

## Latest full workspace and roadmap snapshot

- Immutable WIP path: `/volume1/Saclay/projects/syntelos/work-in-progress/20260724-091531-neyvia-full-workspace-roadmap`
- This snapshot contains the complete safe source workspace, current frontend work,
  backend/runtime integrations, tests, configuration, proof receipts, memory notes,
  and `docs/NEYVIA_AGENT_EXTENSION_MASTER_PLAN.md`.
- It is a continuation snapshot, not a promoted release. The live
  `/volume1/Saclay/projects/syntelos/current` pointer must remain unchanged.
- Full-vision completion at this handoff is approximately 28.5 percent. The master
  plan is the source of truth for completed foundations, acceptance gates, and the
  remaining roadmap.

## Live access

- Live Control URL: `https://nas.example.invalid:47880/control`
- Current project workspace: `/volume1/Saclay/projects/vibe-coding-platform`
- Live release path: `/volume1/Saclay/projects/syntelos/current`
- Runtime stack path: `/volume1/Saclay/projects/syntelos/runtime/bin`

Do not put local passwords or NAS credentials in Git. The generated Neyvia login note stays under `.agent_control` on the machine/NAS.

## Current mission

- Mission title: `Neyvia self-fix mission NAS`
- Runtime requested: `hermes`
- Current behavior goal: mission-first Control UI with readable Hermes/Codex-style runtime reports, real mission snapshots, real runtime event proof, and no fabricated progress.
- Latest verified UI behavior: the mission thread renders delegated runtime output from mission session events instead of only generic control-cycle summaries.

## Important verification already run

- `python -m pytest tests\test_runtime_supervisor.py tests\test_web_backend.py tests\test_mission_control.py -q`
- `npm run frontend:build`
- Live Control folder verification:
  - Projects `+` opens the Add Project dialog.
  - `Browse NAS/server folders` opens the authenticated server-side picker.
  - The picker can open `/volume1/Saclay/projects/vibe-coding-platform` and lists real project folders such as `.git`, `docs`, `scripts`, `src`, and `web`.
  - Selecting the folder fills the project path.
  - Saving a project from that NAS path succeeds after the frontend save handler fix.

## Continuation notes

- Mission launch and login should be possible from another computer if it can reach the Tailnet/NAS URL.
- If Control loads but shows a login page, sign in through the local Neyvia account flow.
- If the app shows generic cycle summaries again, inspect `.agent_control/runtime_sessions/*.events.jsonl`; the real Hermes output should be there and the frontend should group those events into one mission report bubble.
- If Hermes appears unavailable, run the NAS runtime doctor before falling back to another runtime.
- The highest-value next slices are production peer enrollment and private relay,
  real Android/NAS and WAN-distance transfer proofs, multi-peer replication and
  garbage collection, production Matrix and Vaultwarden deployment, modular
  marketplace signing and activation, seamless desktop/mobile app building,
  modern OCR model evaluation, dependency-wide performance work, and the signed
  one-button updater.

Publication note: local account paths and network identifiers in this document are neutral examples.
