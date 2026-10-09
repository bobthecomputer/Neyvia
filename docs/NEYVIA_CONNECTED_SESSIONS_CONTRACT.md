# Connected sessions contract

The shapes live in `src/grant_agent/connected_sessions/model.py`. This file fixes the API between
the broker and the UI, and the module layout.

## Modules

| Module | Owner track | Role |
|---|---|---|
| `connected_sessions/model.py` | lead | shared dataclasses and `Adapter` protocol |
| `connected_sessions/claude.py` | Claude track | Claude Code adapter (official `claude` CLI only) |
| `connected_sessions/codex.py` | Codex track | Codex adapter (one long-lived `codex app-server`) |
| `connected_sessions/opencode.py` | service track | read-only OpenCode adapter wrapping the existing inventory |
| `connected_sessions/broker.py` | service track | runs, cursors, event ring buffer, adapter registry, list merge |
| `connected_sessions/api.py` | service track | the command handler, the SSE stream and the media route |
| `connected_sessions/forward.py` | service track | desktop bridge to persistent service, over loopback |
| `connected_sessions/workspace.py` | service track | git and GitHub state for a session's folder |
| `connected_sessions/seen.py` | service track | per-session "last seen" for unread dots (state root) |

The existing `external_chat_inventory.py`, `connected_app_chats.py`, `connected_claude_chats.py` and
`connected_codex_chats.py` and their commands keep working unchanged until promotion. The served UI
still uses them.

## Where it runs

The broker lives in the persistent PC service (`scripts/run_web_backend.py`, supervised on port
47881). Browser and phone reach it over HTTP. The desktop app's per-command `desktop_bridge`
process must forward the `connected_*` commands to that same local service over loopback, so all
three clients see the same live runs. When the service is unreachable, forwarding returns
`{"ok": false, "code": "pc_service_offline"}` and the UI shows that state.

## Commands (`POST /api/backend`, same names through the desktop bridge)

| Command | Payload | Returns |
|---|---|---|
| `connected_sessions_list_command` | `{query?, app?, includeArchived?, includeHarness?, limit?, offset?}` | `{sessions: [SessionSummary], sources: [{app, available, reason}], host: {deviceId, deviceName}, total, nextOffset, cursor}` |
| `connected_session_read_command` | `{id, cursor?, beforeSeq?, limit?}` | `ItemsPage` plus `{run: RunRecord \| null}` |
| `connected_session_send_command` | `{id, message, requestId, options: TurnOptions}` | `RunRecord` |
| `connected_session_new_command` | `{app, cwd, message, requestId, options}` | `RunRecord` (with the new `sessionId` once known) |
| `connected_session_stop_command` | `{runId}` | `RunRecord` |
| `connected_session_answer_command` | `{runId, requestId, response: {decision, answers?}}` | `RunRecord` |
| `connected_session_compact_command` | `{id}` | `RunRecord` |
| `connected_session_goal_command` | `{id, action: "get"\|"set"\|"clear", text?}` | `{goal: {text, state} \| null}` |
| `connected_provider_options_command` | `{app, id?}` | `Adapter.options()` |
| `connected_session_workspace_command` | `{id}` | see Workspace |
| `connected_session_file_diff_command` | `{id, path}` | `{path, patch, truncated}` |
| `connected_session_git_action_command` | `{id, action: "commit"\|"push"\|"create_pr", message?, title?, body?, confirm: true}` | `{ok, output, url?}` |
| `connected_session_mark_seen_command` | `{id, seq}` | `{ok}` |
| `connected_events_poll_command` | `{cursor, waitSeconds? <= 20}` | `{events, cursor, resync?: bool}`, the long-poll fallback |

`RunRecord` has these fields:

```
{runId, sessionId, app, state: RunState, startedAt, updatedAt,
 pendingRequest: {requestId, kind: "approval"|"question", ...Item.data} | null,
 error: str | null, canStop, canSteer}
```

Rules:
- Runs are durable. Reuse `.agent_control/connected_chats.sqlite3` with a new table.
- `requestId` makes sends idempotent.
- A run whose owner process died becomes `interrupted` and is never resent.

## Live events (`GET /api/connected/events?cursor=N`, `text/event-stream`)

- Auth works exactly like `/api/backend`.
- Each event is `data: <json>` plus `id: <cursor>`, using the event shapes in `model.py` with
  `cursor` added.
- Heartbeat comment every 15 s.
- If `cursor` is older than the ring buffer, send `{"type": "resync"}` first. The client then
  re-reads the list and the open session.
- `session.updated` events are also emitted when `live_status()` changes for sessions the broker
  does not own, polled no faster than every 2 s and only while at least one client is subscribed.

## Workspace (`connected_session_workspace_command`)

```
{cwd, exists, repo: {root, name, remoteUrl, github: {owner, name, url} | null} | null,
 branch, upstream, ahead, behind, worktrees: [{path, branch, current}],
 changes: [{path, status, additions, deletions}], changesTruncated,
 pullRequest: {number, title, url, state, checks: "passing"|"failing"|"pending"|null} | null,
 gh: {installed, authenticated, reason}}
```

- It is read-only.
- Mutating git or GitHub actions go only through `connected_session_git_action_command` with
  `confirm: true`.
- `gh` is used only when it is installed and already signed in. Neyvia never stores GitHub tokens.

## Invariants

- One turn per session at a time. If the app itself is running that session (Claude:
  `claude agents --json` shows it; Codex: an open turn in the rollout or thread status), a send is
  refused with `code: "session_live_elsewhere"` and the owner is named. Never start a silent copy
  or fork.
- No hard time limit on a healthy turn. Only an idle-without-output watchdog, at 30 minutes or
  more, may stop a turn, and it reports that as `interrupted`.
- Every child process is started hidden on Windows.
- Credentials and tokens are never read, stored or relayed.
- Bounded payloads: tool output ≤ 8 KB per item in pages (full output on demand), items page
  ≤ 200, event ≤ 64 KB.

## Deviations and extensions

This section records where the running service differs from, or adds to, the text above. The
service track owns it.

### Extra commands (additive)

| Command | Payload | Returns |
|---|---|---|
| `connected_session_steer_command` | `{runId, message}` | `RunRecord`. Adds a message to a running turn. Refused with `not_supported` unless the run's `canSteer` is true and the adapter has `steer`. |
| `connected_session_tool_output_command` | `{id, itemId}` | `{itemId, output, truncated}`. The full output of one tool item (up to 1,000,000 characters); pages carry at most 8 KB of it and mark `data.outputTruncated`. `not_supported` when the app keeps no full output. |

`connected_sessions_list_command` also accepts `category: "connected" | "native" | "hybrid"`. With no
`category`, every category comes back. `app` accepts `claude-code`, `codex`, `opencode`, `neyvia`
(and the aliases `claude`, `claude_code`, `open-code`). `sources` always lists all four apps.

### Answers and errors

- Success over HTTP is `{"ok": true, "data": <result>}` with status 200.
- A refusal is `{"ok": false, "code": <stable code>, "error": <text>, "message": <same text>, ...extra}`
  with a real status: 400 bad request, 404 not found, 409 conflict, 429 too many streams,
  502/503/504 adapter or app trouble, 500 (`internal_error`) for a bug. Extra keys carry detail, for
  example `runId` on `session_busy`, `owner` (`"app"` or `"cli"`) and `ownerDetail` on
  `session_live_elsewhere`.
- Codes the UI can rely on: `session_live_elsewhere`, `session_busy`, `request_id_conflict`,
  `cannot_continue`, `cannot_start`, `adapter_unavailable`, `session_not_found`, `run_not_found`,
  `request_not_pending`, `request_already_answered`, `invalid_response`, `confirmation_required`,
  `not_a_repo`, `path_outside_repo`, `wrong_device`, `wrong_state_root`, `too_many_streams`,
  `not_supported`, `pc_service_offline`. An adapter's own coded errors (`exc.code`, optional
  `exc.owner`) pass through unchanged.
- Model dataclasses (`SessionSummary`, `Item`, `ItemsPage`, `ContextUsage`) are serialized with
  `dataclasses.asdict`, so their keys stay snake_case (`updated_at`, `has_earlier`). Shapes the
  broker owns (`RunRecord`, events, workspace, list envelope) are camelCase as written above.
  List rows gain one key, `unread`.
- Timestamps in `RunRecord` are ISO-8601 UTC strings.

### Sessions, ids and runs

- Every adapter, the Neyvia one included, uses ids of the form
  `external:<app>:<deviceId>:<quoted native id>` (`broker.make_session_id`). The broker hands
  adapters and takes back full ids; a bare native id in an event or a return value is wrapped.
- `runId` of a send is its `requestId` (so a replay is a plain lookup). A compact run is
  `compact-<uuid>`.
- A run is `queued` until its worker starts. A `new` run holds the request for up to 15 s for the
  adapter to name the session, so the returned `RunRecord` usually carries `sessionId`.
- Sends are refused with `cannot_continue` when the session's `capabilities.continue_session` is
  false (the adapter's `reason` is the message), and `session_live_elsewhere` (HTTP 409) when the
  app runs the session.
- `canStop` is the session's `capabilities.stop` (true for a new session); an adapter may change
  `canStop`/`canSteer` by adding them to a `run.state` event.
- Idle watchdog: 30 minutes without any event from a `queued`/`running` turn stops it and marks it
  `interrupted`. `NEYVIA_CONNECTED_IDLE_SECONDS` may raise, never lower, the limit. A turn that waits
  for an approval or answer is never stopped by it.
- After a crash or restart, runs whose owner process is gone (or whose PID was reused) become
  `interrupted` with a message saying they were not resent. A replay of the same `requestId` returns
  that record.
- A second answer for the same `requestId` is `request_already_answered`.

### Events

- The cursor is a millisecond timestamp plus a counter, so a cursor from before a service restart is
  older than the new buffer and always gets `resync`. A cursor newer than the service (or older than
  the buffer) gets `resync`. A subscriber with no cursor hears only what happens from now on; the
  list result's `cursor` is the position to subscribe from.
- Buffer: 5,000 events and 24 MiB. An event over 64 KB has its largest strings cut and carries
  `truncated: true`.
- Every event carries `cursor` and `hostDeviceId`. The broker normalises `run.state` (it always has
  `sessionId`, `runId`, `state`, `pendingRequest`, `error`), and adds a `session.updated` after a run
  changes state so lists stay current without help from the adapter.
- `Last-Event-ID`, when a browser reconnects, wins over the `cursor` query. Frames are
  `id: <cursor>` then `data: <json>`. The first bytes are `: connected` and `retry: 3000`. A
  heartbeat comment goes out every 15 s. The response sends `X-Accel-Buffering: no`.
- At most 64 streams; a 65th gets 429 `too_many_streams`. A closed connection is noticed within
  about a second and frees its thread and its subscription.
- Live-status polling starts with the first stream or long-poll and continues for 5 s after the
  last one leaves. A long-poll (`connected_events_poll_command`) counts as a subscriber while it
  waits. A first long-poll with no `cursor` returns at once with the current `cursor`.

### Media

Attachments carry `url: "/api/connected/media?session=<id>&media=<attachment id>"`, served with the
same login as `/api/backend`. The broker rewrites any other URL an adapter gives, and reduces a
label that looks like a path to its file name, so a host path never reaches a client. Bytes come
from the adapter's `media(session_id, media_id)` or `read_media(...)`, else from
`connected_chat_media.read_media`. Images are served inline, everything else as an attachment with
`nosniff`.

### Adapter registry and optional hooks

The broker builds an adapter the first time it needs it, in this order: a factory registered with
`register_adapter(app, factory)` (process wide) or `ConnectedBroker.register_adapter`; then the
module `connected_sessions.<claude|codex|opencode|neyvia>` through `create_adapter(...)`,
`build_adapter`, `get_adapter`, `make_adapter`, then a class named `ClaudeAdapter`,
`ClaudeCodeAdapter`, `CodexAdapter`, `OpenCodeAdapter`, `NeyviaAdapter` or `Adapter`. A registered
factory is called as `factory(backend)`. A module factory or class that has a parameter called
`backend` gets the backend; the Neyvia adapter's first positional parameter gets it; other adapters
get the state root when they take a `root`, `state_root`, `workspace_root` or `base_dir` argument,
else nothing. A missing module, a failing import or constructor, or an object without the eight
`Adapter` methods makes that app an unavailable source with the reason; a failed load is retried
after 30 s.

Optional methods the broker uses when an adapter has them:

| Method | Use |
|---|---|
| `preflight(session_id \| None)` or `check_send(session_id)` | Called before a send, compact or new session; raise an error with `.code` (and `.owner`, a name or a dict with `owner`) to refuse. |
| `can_start_new() -> (bool, reason)` | Refuse `connected_session_new_command` with `cannot_start`. |
| `compact(session_id, *, run_id, emit)` | Run a compaction as a run. Without it, `/compact` is sent as a turn when the session's `capabilities.compact` is true. |
| `goal(session_id, action, text)` | `connected_session_goal_command`. Without it, `get` answers `{goal: null, supported: false}` and `set`/`clear` are `not_supported`. |
| `steer(run_id, message)` | `connected_session_steer_command`. |
| `tool_output(session_id, item_id)` | `connected_session_tool_output_command`. |
| `media` / `read_media(session_id, media_id)` | The media route; return `(bytes, mime, name)` or `None`. |
| `set_event_sink(emit)` | Called once with a function that publishes events belonging to no run the broker started (goal turns, renames). |
| `close()` | Called when the broker closes and at process exit (Codex's app-server). |

### Workspace

- Extra keys: `detached` (true on a detached HEAD), `gitError` (only when git cannot read the folder),
  `pullRequestError` (only when `gh` could not read the pull request), and per change `staged` and,
  for a rename, `oldPath`. `status` values are `modified`, `added`, `deleted`, `renamed`, `copied`,
  `typechange`, `untracked`, `conflicted`. `pullRequest.state` is lower case (`open`, `closed`,
  `merged`). `ahead` and `behind` are `null` when the branch has no upstream. Binary files have
  `null` counts.
- Cache: 5 s for the folder state; 15 s for a pull request and 60 s for `gh auth status`, because
  those ask GitHub. Any git action drops the cache.
- `remoteUrl` never carries `user:token@`. Nothing here reads a GitHub token or `gh`'s config; `gh`
  is asked only for `auth status`, `pr view` and, with `confirm: true`, `pr create`.
- `commit` is `git commit -a -m <message>` (tracked changes only; untracked files are left alone).
  `push` is `git push` when the branch has an upstream, else `git push --set-upstream <origin or the
  only remote> <branch>`; it never forces. `create_pr` is `gh pr create --title --body`. `confirm` must
  be the boolean `true`. Output is the command's real stdout and stderr, cut at 20,000 characters.
- File diffs are limited to the repository (a path that resolves outside it, by `..`, absolute path or
  symlink, is `path_outside_repo`) and to 256 KB, then end with `... [diff truncated]`.

### Desktop parity

`desktop_bridge.py` lists every `connected_*` command in `ALLOWED_DESKTOP_COMMANDS` and hands them to
`connected_sessions/forward.py`, which:

1. connects to `http://127.0.0.1:<port>` with no system proxy (`NEYVIA_CONNECTED_SERVICE_PORT`, else
   `NEYVIA_WEB_PORT`/`FLUXIO_WEB_PORT`, else 47881);
2. signs in with the service's existing loopback bootstrap `POST /api/auth/local-session` (it needs no
   password and works only from this PC, with a loopback `Host`, and while the service has no public
   URL), the same mechanism the connected-chat commands already use;
3. posts `{command, payload: {..., _expectedStateRoot: <desktop state root>}}` to `/api/backend`, then
   signs out. The service refuses a different state root with `wrong_state_root`.

The bridge returns the service's `data`, or, for a refusal, the refusal object as the command's
**result** (`{"ok": false, "code", "message", "error"}`), because the Tauri layer turns an envelope-level
failure into a bare string and would lose the code. The desktop client should treat a result whose
`ok === false` as an error. Bridge-only codes: `pc_service_offline` (nothing is listening),
`pc_service_auth` (the local sign-in was refused), `pc_service_timeout`, `pc_service_error`. Timeouts:
30 s, 45 s for `new`, `waitSeconds` + 15 s for the long-poll, 200 s for git actions. Send and new requests
may carry up to 26 MiB (pasted images). A desktop window that wants live events polls
`connected_events_poll_command` through the bridge, or opens `/api/connected/events` on
`http://127.0.0.1:<port>` after the same local sign-in (the cookie is `HttpOnly`, so use `fetch` with
credentials, not a script cookie).

A browser or phone that reaches the service with the `X-Neyvia-Controller: desktop` header is still
served by the service directly; connected commands never go through the desktop controller queue.

### Not done

- Archive, unarchive and rename (the Codex adapter has them) have no command yet.
- Access is the same as `/api/backend`: any signed-in account. There is no extra owner-only check on
  send or the git actions.
