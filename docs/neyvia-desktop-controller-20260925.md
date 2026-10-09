# Neyvia desktop controller — 25 September 2026

## Requested behavior

Use the same running PC app from another device. A phone gets the responsive phone layout; another PC gets the desktop layout. Conversations, saved system prompts, model choices, tool execution, and artifacts belong to the host PC.

Private entry point: <https://asuspsdlb.example.invalid:8443/control?surface=agent&controller=desktop>.
Tailscale and Neyvia must be running on ASUSPSDLB. The remote device must be on the same tailnet and sign in with the existing Neyvia owner account.

## Implementation

- `desktop_controller.py` provides a bounded SQLite command relay, request IDs for retry deduplication, PC process identity and liveness, and explicit offline errors. Only a child of the installed Tauri process can claim or complete commands. Completed payloads are compacted; credential values are not relayed.
- `web_backend.py` requires the authenticated owner and same origin for controller requests. The native desktop executes actions through its existing dispatcher. Observational transcript, summary, and provider-presence reads use the shared root directly after checking that the desktop is online, so refresh traffic does not delay desktop actions.
- `desktop_bridge.py` reuses the existing conversation and prompt helpers without constructing the full backend for every refresh. Execution continues through the real desktop runtime.
- `NeyviaShell.jsx` runs the desktop relay client and shares session metadata, route, prompt profile, pending turns, and streaming events. `NeyviaWorkspace.jsx` displays the connection and resumes shared conversations in the existing UI.
- Conversation saves merge under a cross-process SQLite lock. A stale client cannot replace a completed reply with a pending one, and an empty route from a new browser cannot erase the saved model or workspace. Workspace hydration preserves the conversation's selected model; an explicit local model change also survives reload.
- The desktop reads `%APPDATA%/com.neyvia.desktop/desktop_controller_root.json` before choosing a default root. This installation is pinned to `C:\Users\example\Projects\Neyvia`, including ordinary Start menu launches. Explicit execution workspaces remain supported.
- Device links now point to controller mode. Port 8443 serves Neyvia through Tailscale; the existing port 443 Dictation mapping remains intact.

## Verification and evidence

Evidence lives in `proof/desktop-controller-20260925/`.

- Queue verification: replay behavior, process expiry, Windows canonical paths, 140 completed requests, bounded stored results, and a running task surviving the old three-minute cutoff.
- Shared-state verification: concurrent sessions, final reply preservation, route/prompt metadata, and tool traces.
- HTTP verification: unauthenticated status rejected, host-only commands rejected over HTTP, foreign origins rejected, and offline controller requests fail without another execution path.
- First live phone-layout task used DeepSeek V4.1 Flash through the installed app to write and read `from-phone.txt` on ASUSPSDLB. Independent SHA-256: `c55de7983f785bd8964d1a0fb2279c7d254ac90022dad2ed58a0174feb4f0070`. That run exposed the desktop transcript display bug, so its receipt is retained as failed end-to-end evidence.
- `remote-prompt.json` proves the phone editor reads exactly the desktop's saved chat system prompt. The file import control is present. This check did not alter the saved prompt.
- `laya-installed-navigation.json` records four real installed-app navigation actions, independently checked, with no physical cursor movement. This is bounded Neyvia navigation proof, not generic desktop coverage.
- `verified-live-controller.json` confirms the final real DeepSeek task: the installed desktop and phone display the same immutable turn, exact final reply and tool trace. Both showed live tool activity; the desktop showed provider thinking. The independent file hash matched. Seven tool calls ran, including two failed attempts that the model recovered from. Total observed time was about 67 seconds; this is functional evidence, not a controlled latency benchmark.
- `responsive-controller.json` reopens that completed task with fresh browser storage at 390 × 844 and 1440 × 960. Both show the saved workspace and DeepSeek model, the corresponding phone/desktop navigation, a live connection, no horizontal overflow, and no page errors.
- `route-reselection.json` checks that a user can select Luna, reload with that selection intact, then return to DeepSeek. It sends no provider task.
- `installed-reopen.json` confirms that the final installed app reopens the shared task, restores DeepSeek, and exposes all seven recorded tool calls and their input. `packaging.json` matches 11 installed Python modules and the packaged executable to source/build; the saved prompt hash is unchanged.
- `offline-final.json` records the desktop being closed and the controller returning 503. `normal-runtime.json` and `http-boundary.json` confirm the normal installed launch reconnects and the temporary diagnostic port is closed.
- `laya-final-installed-navigation.json` records four passing actions on the final normally launched installed app (PID 50612), with fresh postconditions, in about 5.2 seconds. This is the existing bounded navigation workflow.

## Limits and preservation

Phone and second-PC layouts are exercised with browser viewports on the host over the real Tailscale URL. A separate physical phone or PC has not been operated by this verification. This controller operates Neyvia tasks and their PC tools; it does not mirror the Windows screen.

The desktop must stay open and the PC awake. Remote tools use the selected conversation's existing access mode. Provider credentials remain on the PC. This is a local installed WIP checkpoint, not a public release or a claim that every provider and tool combination was tested.

Dirty source and existing prompts/history were preserved. The previous NAS WIP was reconciled before editing. A successor snapshot includes the source, installer, and bounded proof; it excludes authentication state and controller databases.

Publication note: local account paths and network identifiers in this document are neutral examples.
