# No automatic chat time budget — 25 September 2026

The user's correction, "No budget", supersedes the one-hour default described
in `neyvia-runtime-completion-20260925.md`.

## Behavior

- Active chat requests have no automatic elapsed-time deadline in the Tauri
  bridge, web backend, provider runtime wrapper, Native run, or desktop controller.
- Legacy timeout environment defaults no longer silently end chats. An explicit
  timeout supplied by an API caller remains opt-in.
- Individual network operations, short status requests, and requests which no
  desktop has claimed retain their separate failure detection. They do not
  impose a total duration on an active chat.
- A Stop control requests cancellation of the selected chat turn. The owning
  backend stops its own runtime process; the UI waits for the final result.
  Cancellation is isolated by turn ID and invocation token. It does not replay
  commands or roll back actions which already happened.

## Verification and deployment

Evidence for this correction is under `proof/no-run-budget-20260925/`.

- The production Rust wait helper completed a real 181-second PowerShell process
  with its deadline set to `None`. The same check covered explicit short timeout
  cleanup and independent status-query deadlines: three checks passed.
- Controller fixtures check that an active unlimited chat survives elapsed time,
  while explicit deadlines and unclaimed/offline detection remain functional.
- Backend fixtures passed ordinary completion without a deadline, real process
  cancellation and reaping, persisted cancellation, and prevention of provider
  fallback after Stop. Dispatch checks passed with both legacy timeout environment
  variables present. Controller checks include a reserved cancellation slot when
  four chats and the ordinary queue are full.
- Seventeen focused frontend checks passed. The first live check found that the
  old transcript source filter hid the stopped reply. The shared filter now
  recognizes cancellation, and a second live Stop showed the reply immediately.
- The final NSIS build is installed and running as PID 49584. Its executable and
  sixteen backend modules match the built source; the user's saved prompt hash
  remains unchanged. The backend on port 47881 was restarted with the new code.
- LAYA completed its four-step installed desktop navigation workflow in 3.68s.
  This proves that named navigation journey, not generic desktop automation.
- Through the desktop controller, Neyvia Native / OpenCode Go / DeepSeek V4.1
  Flash was started and stopped. The final receipt confirms both process tree
  termination and reaping. "Stopped by you" appeared without reloading. The
  stopped turn also survived reopening; a subsequent live model request returned
  "Ready." normally. See `live-cancellation-final.json`, `live-follow-up.json`,
  `stopped-final.png`, and `verification.json` in the proof folder.
- A controller tab loaded during the rebuild briefly referenced an old deleted
  asset. Reloading recovered it and the saved response. Future live builds should
  stage assets before replacing the served distribution.

The recoverable NAS WIP transfer is recorded in `nas-transfer.json`. No public
release is promoted by this checkpoint.

This change removes the application's automatic elapsed-time budget. Provider
errors and independently configured model/tool operation limits can still end
an operation; it does not promise that a provider connection lasts forever.
