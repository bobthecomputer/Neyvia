# Desktop prompt, Explorer, and provider streaming repair

## Requested result

The installed Neyvia desktop must use Explorer when adding a workspace, let an
authored system prompt replace Neyvia's stock chat instructions, and display real
provider text deltas before the reply is complete. Text and Markdown prompt files
must be importable. Keep the user's existing prompts and workspaces.

## Implementation

- `NeyviaShell.jsx`: desktop workspace actions use the existing native folder
  picker; selecting a folder updates the form path and automatically derived
  defaults without replacing names the user has explicitly customized.
- `NeyviaPromptEditorDialog.jsx` and `src-tauri/src/lib.rs`: native text/Markdown
  import, cancellation, bounded UTF-8 input, saved effective prompt preview.
- `agent_prompt_library.py`: distinguish authored Shared and role prompts from
  serialized defaults. An authored Chat prompt alone replaces both stock blocks;
  authored Shared and Chat text compose only when both are customized. Normalize
  Windows line endings while preserving the rest of the text.
- `neyvia_agent.py`, `web_backend.py`, and `codex_app_server_stream.py`: remove
  stock persona/task suffixes from custom prompt paths; use actual Codex base
  instructions rather than a lower-priority appended message.
- The Native SDK path requests streaming for Responses and Chat Completions,
  forwards actual provider deltas and tool events, distinguishes answer identities
  across tool rounds, and reports stream failure without a hidden nonstream retry.
- `chat_stream.py`: bounded JSONL frames preserve long Unicode output;
  `desktop_bridge.py` serves stream reads before expensive backend initialization
  and accepts both flat and Tauri-wrapped command payloads.
- `neyviaChatStream.js` and `NeyviaMessageBody.jsx`: shared event accumulation and
  cancellable polling; render text as it arrives without an artificial typing queue.
- Removed focus-mode paragraph clamping from dialogue messages, corrected the
  star/reasoning label layout, and disabled the obsolete composer pseudo-cursor.

### Confirmed desktop failure

The new lightweight reader initially bypassed `FluxioWebBackend.dispatch`, which
normally unwraps `{payload: {turnId, cursor}}`. The early reader looked for
`turnId` on the outer object. A real IPC call returned `Invalid chat turn id`;
after normalization the same call returned 210 events, `ready=true`, in 503 ms.
The installed UI then rendered intermediate text. Earlier hypotheses about a
missing command route and a long-held interpreter lock were disproved.

## Evidence and acceptance

Evidence lives in `proof/provider-fixes-20260924`.

- Local Node protocol fixture exercises the actual Native CLI against controlled
  Responses and Chat Completions SSE endpoints, including a real local read-tool
  round trip. It checks exact custom instruction bytes after newline normalization,
  stream request flags, deltas before completion, final text, and provider errors.
- Early UIA samples were insufficient for reliable stream timing. A direct DOM
  observer in the installed Tauri WebView confirmed no intermediate rendering
  before the bridge fix (`deepseek-final-a.json`, `deepseek-final-b-diagnostic.json`).
- After the fix, `deepseek-working-b.json` records 203, 888, and 1,242 characters
  in three pending frames, then the same 1,242-character answer at completion.
  A second DeepSeek run also passed. `luna-working.json` explicitly verifies the
  selected GPT-6 Luna model and records five pending frames (82 to 1,102 characters)
  followed by the complete 1,122-character response.
- These are real provider requests through the installed desktop. Whole-turn
  times were about 25 s for the first passing DeepSeek run and 19 s for Luna with
  intentionally long test replies. They do not isolate provider latency or prove
  zero local overhead. Polling still has process/IPC and scheduling overhead.
- Native `.md` and UTF-8-BOM `.txt` imports saved text exactly after normalizing
  Windows newlines. Changing the saved Chat prompt in the same conversation
  changed DeepSeek from a French `NEYVIA_LIVE_A` reply to an English `NEYVIA_LIVE_B`
  reply. Luna also followed the B prompt. Cancelling file import preserved the store.
- Native Explorer folder selection populated the project path and derived name.
  Cancelling the picker preserved the selected workspace; cancelling the add-project
  form avoided creating a test profile.

- Frontend and Node bridge integration suite: 124 passed. The bridge fixture runs
  the real Python CLI from Node and checks wrapped/flat payloads, partial lines,
  Unicode, cursor continuation, and invalid IDs. No pytest suite was run.

Final installer, navigation, and restoration receipts are recorded alongside the
provider evidence. Private prompt backups are outside the proof bundle.

### Final installed package

- `installation-release.json`: installer SHA-256
  `394BACF498DEB253A3089ED4241362379546AA792C165FB49EC0A1036E9D2DA6`,
  13,619,024 bytes, installer exit 0; installed bridge matches source.
- `release-deepseek.json`: the final package rendered 355, 1,008, and 1,729
  characters while pending, followed by the identical complete answer. Paragraphs
  have no line clamp; their client and scroll heights match. During streaming the
  legacy composer cursor is absent and the redundant reasoning caption is hidden.
- `laya-installed.json`: completed with `postcondition_verified`, worker
  `passed=true`, exact installed process 29864. Laya's supported navigation journey
  completed in 3,647 ms, without foreground activation or physical cursor movement.
  This receipt covers navigation; native import and live replies have separate proof.
- `restoration.json`: original prompt file restored byte for byte, RentSecurity
  workspace and DeepSeek V4.1 Flash restored, diagnostic listener stopped. The app
  was relaunched normally. The local web route on port 47881 returns HTTP 200.
- Backend source and packaged source hashes are checked in
  `installed-source-consistency.json`. The NAS WIP transfer receipt is saved locally
  as `nas-transfer.json`; this is a recovery snapshot, not a public release.

## Scope of the claim

Exact outbound prompt composition is under Neyvia's control. An upstream provider
can still enforce its own policies, and a model is not guaranteed to obey every
instruction. The protocol fixture covers two API transports; it does not establish
live availability or behavior for every provider account. Laya's named desktop
navigation workflow proves only those supported navigation transitions.
