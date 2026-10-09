# Stuck responses after a crash, Stop, and readable tool activity — 25 September 2026

## What went wrong

A Neyvia Native turn in *Hey spinach* (RentSecurity) was streaming at 16:02 when
the desktop app went down. At the same moment Windows recorded Claude and
ChatGPT hanging, and the WSL virtual machine shut down at 16:03:05, so it looks
like a system-wide stall rather than a Neyvia-only crash.

After reopening:

1. The turn's run record still said `running`, owned by process 57964, which no
   longer existed.
2. The window restored the pending turn and replayed its saved event stream
   (1.2 MB, 12 tool calls), so it looked as if it was still working.
3. That stream never got its end marker, so the window waited forever.
4. Stop wrote a stop file for the owner, which was gone. The toast said "Stop
   requested" and nothing else ever happened.

## Changes

**Backend (`chat_run_control.py`)**
- A run records its owner's OS start time, and every runtime child it spawns
  (`note_runtime_process`). A reused PID is not mistaken for the owner.
- `chat_run_status` / `get_agent_chat_run_status_command` report whether a
  turn is really running. If the owner exited, the turn is marked
  `interrupted`, leftover runtime children with a matching identity are
  stopped, stale stop files are removed, and the event stream is closed with
  `runtime.done` / `interrupted`.
- Stop on a turn whose owner exited returns `interrupted` immediately.
- The final result of every turn (reply, failure, or cancellation) is saved
  to `.agent_control/chat_runs/results/` before the stream closes, so a window
  that reconnects can show it.
- The desktop bridge answers stop and status without building the whole
  backend, and no longer fails when the window that asked has gone.
- Chat sends are not retried over Tauri IPC. A retry after a timeout-like
  error could run the same turn twice.

**Frontend**
- `neyviaChatRecovery.js` decides, for each pending turn this window is not
  waiting on: keep watching (the process is alive), settle with the recorded
  result, or settle as interrupted. The full stream is replayed first, so an
  interrupted turn keeps all partial text and tool calls. Unfinished calls
  are marked *Interrupted*.
- Interrupted turns, and stops that kept partial text, now say so, with
  **Continue from here** and **Restore original message**.
- Stop in a window that did not send the turn settles it itself.
- A running response that has been silent for 90 seconds says "No new output
  for N min. You can keep waiting or press Stop."

**Tool activity**
- `neyviaToolCallPresentation.js` + `NeyviaLiveToolTrace.jsx`: commands show
  the command line with its shell prompt, working folder, exit code, duration,
  and collapsible stdout/stderr. File writes and edits show line-numbered
  diffs with +/− counts, covering `workspace.write`, string-replace edits, and
  `apply_patch`. Reads show the file. Raw JSON remains under "Raw tool input
  and result". The last 8 calls show by default, with a link for earlier ones.
- `workspace.write` returns `linesAdded`, `linesRemoved`, and a unified diff
  capped at 6,000 characters for updates.
- `terminal.exec` sets `WSL_UTF8=1` and repairs UTF-16 output read as UTF-8
  (the `N\0A\0M\0E` text from `wsl.exe`).

## Verification

- Backend: against a copy of the real stuck turn, Stop returned `interrupted`,
  the stream closed once, and the stale stop file was removed. A simulated
  crash with a live orphaned runtime child stopped the child. Stop on a live
  owner still cancels. The existing no-deadline/Stop verifier passes all seven
  checks.
- Frontend: 157 `tests/*.mjs` and 150 `web/src/neyvia/*.test.js` checks pass,
  including new recovery and tool-presentation tests built from real stream
  payloads.
- Browser, against a scratch copy of the conversation store: the stuck turn
  settled as interrupted with its 12 tool calls and partial answer. A
  simulated surviving owner was followed live and then settled with its
  recorded reply. After the quiet hint appeared, Stop from that window
  cancelled the owner within about 5 seconds.
- Known unrelated failures: `test_desktop_bridge_installs_and_allows_the_bundled_image_skill`
  (no `.codex/skills/imagegen` in this checkout) and six `test_web_backend.py`
  checks that still expect the pre-"no budget" prompt and timeout behaviour.
