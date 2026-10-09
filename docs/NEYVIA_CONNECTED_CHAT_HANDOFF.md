# Neyvia connected app chats

## Product distinction

- **Connected app chats** are sessions owned by a supported coding app on a connected host. Neyvia reads those host sessions and, when the host explicitly reports send support, sends a message back into that same session. They are not Neyvia Hybrid sessions.
- **Neyvia Hybrid** groups Neyvia-owned conversations executed through an external agent harness (including Codex, Claude Code, Hermes, and the explicit hybrid route). The conversation belongs to Neyvia; whether the harness also shows it in its own app is incidental.
- **Neyvia Native** refers to Neyvia's first-party/native runtime and tools. It is also separate from both connected host sessions and Hybrid.

The readable connected-chat view covers Codex and Claude Code host sessions. **Open Codex live / Open Claude live** opens the actual installed Windows app window inside the authenticated Neyvia page. This is a separate presentation of the real app, including its current sidebar, account, context menus, usage display and new-session controls. It does not reconstruct app state from transcript files or sign in to the provider again.

The live window view requires the host desktop to be awake and unlocked. Only the installed Codex and Claude WindowsApps executable identities are accepted. Captures are window-only; input uses a fresh, single-use frame token and rechecks process identity, geometry, input desktop and click target. The user chooses when to open, pause or close the view. Other host activity can interrupt control. It is a low-rate image view with click/right-click, scrolling, text and selected keys, not a video stream or complete remote desktop. Cross-device file upload, drag operations and dialogs owned by other processes are not implemented.

## Backend interface

`get_external_chats_command({ app, query, limit })` lists sessions available on the active connected host. The result carries host/device information and per-source availability. `get_external_chat_command({ id })` returns `{ chat, messages, truncated, capabilities }`, where each message may contain `attachments: [{ id, label, url, kind }]` and `kind` is `image` or `file`. `capabilities.canSend` is authoritative; when false, `capabilities.reason` should explain why the transcript is read-only.

For a send-capable chat, Neyvia calls `send_connected_app_chat_command({ id, message, requestId })` and receives `{ runId, state }`. It polls `get_connected_app_chat_run_command({ runId })`; `{id:chatId}` instead recovers the latest run after reopening the page. A pending Codex request remains attached to the same app-server process and appears as `pendingRequest`. `answer_connected_app_chat_command({runId,pendingId,response})` answers it; `cancel_connected_app_chat_command({runId})` interrupts only that run's Codex turn. Stale/repeated answers are rejected, answers are not persisted, and grants apply to that turn. Native app policies remain authoritative. A 24-hour pending wait does not consume the execution timeout.

Conversation discovery supports `offset` and returns `nextOffset` and `total`; the UI can load beyond its initial 80 rows. Context counters come from source usage events, not transcript length or cumulative billing totals. Missing model windows and compaction thresholds remain unknown. The live app view exposes the source application's own richer usage controls.

The UI must not fabricate transcript entries or report a successful send before the backend run reports completion. If the transcript command fails, retain an explicit error. If sending is unsupported, keep the transcript readable and show the backend-provided reason. Do not ask for credentials in the chat UI: host login and session availability are owned by the connected-host flow.

## Follow-up preview

After the working build is delivered, Opus must develop in a separate checkout and preview port. Do not rebuild over the served directory, restart the serving process, or change Tailscale routes during UX iteration. The user monitors work through the browser, so attach screenshots and output artifacts to the actual host chat and verify that they render there. Promote a completed, checked candidate separately. Before this delivery the app was not yet usable; this isolation requirement is for subsequent development, not a reason to defer the current repair.

The sidebar offers All plus the three categories above. Native/Hybrid classification uses the latest durable runtime where available. Unknown historical routes and mixed orchestration stay visible in All; they are not guessed from a provider name.

Provider credentials stay on the host. Browser clients authenticate to Neyvia once; they do not repeat Codex/Claude provider sign-in. Neyvia web sessions persist for 30 days across backend restarts and are revoked on logout or account credential change. Cookies from the older in-memory session implementation cannot be recovered after its process exits.

## Verification boundaries

Codex same-session continuation was verified on a disposable real app-server thread in the earlier delivery. The new approval broker passed a production-manager fixture round trip, reload recovery, cancellation and stale-answer checks; a new real-model approval round trip has not yet been verified. Claude Code's earlier live CLI request timed out. Its Desktop Code session UUID was independently matched to the local inventory and running official CLI, but the CLI adapter cannot control a turn already running in Desktop. Use the live app window for actual Desktop interaction. OpenCode history is readable; its send adapter is not implemented. Historical transcript views remain bounded excerpts with local image/file references.

The live-window browser journey on 2026-09-29 opened Claude's actual New screen, typed and cleared an unsent Unicode draft, and operated Escape in its actual menu. Codex's real window rendered at a 390×844 browser viewport. These checks do not establish every app control or physical iPhone behavior. A separate Computer Use inspection opened Claude's usage breakdown, which added the native `/usage` command to the existing session; no model run was started.

Connected sends must run in the persistent web service. Do not dispatch their background workers in a short-lived desktop Python process. The remote desktop-controller route handles these commands in the service, and direct desktop sends forward to the loopback service with an expected state-root check.
