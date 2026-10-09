# Automatic compaction and ordered activity — 2026-09-28

## Changes

Native SDK chat now creates a durable semantic continuity checkpoint automatically at the model-input boundary. It no longer relies on dropping older turns for its main provider path. The checkpoint records goals, constraints, decisions, observed completions, pending work, failures, files, and next steps. It uses the selected provider/model without executing tools. The executor's authored system instructions and reasoning settings remain unchanged.

Full SQLite history remains saved. A rolling source hash validates cached checkpoints; changed prefixes invalidate them. Compaction preserves complete tool-call/result groups and the current user request, including long multi-tool turns. Valid intermediate checkpoints survive interruption. Invalid or empty summaries cannot replace a valid checkpoint; malformed output gets one bounded retry, then an explicit recoverable error.

Replay uses conservative character/record budgets (240,000 characters or 400 records trigger compaction; recent tail targets 120,000 characters / 200 records). This is not a universal token-optimal policy for every model. The verified DeepSeek V4.1 Flash / OpenCode Go route uses larger bootstrap summary batches within its observed 1M-token context limit. Other providers retain smaller batches. Large historical tool payloads are excerpted for summarization; their full records remain in SQLite.

DeepSeek checkpoint requests use its documented [JSON mode](https://api-docs.deepseek.com/guides/json_mode/) and [thinking-disabled setting](https://api-docs.deepseek.com/guides/thinking_mode/). This applies only to bookkeeping. Actual model execution retains the user's settings. Public thinking summaries are displayed; raw reasoning records are excluded.

Live activity and saved receipts now preserve chronological public summary/tool segments. Tool completion updates the original card by call ID. Expanded mode shows all recorded summary text and tool cards by default; optional compact mode persists across reload. Older receipts without timing order are explicitly marked as unavailable rather than inventing chronology.

## Verification

- `node scripts/verify-session-compaction.mjs`: production boundaries with disposable provider fixtures; unchanged source history, call/result grouping, current-request retention, checkpoint reuse, prefix invalidation, malformed-output retry, interrupted continuation, ordered receipts and full summary preservation.
- `node --test web/src/neyvia/neyviaChatStream.test.js`: 5 passing checks, including long summaries, 111 activity segments / 55 tools, legacy unknown-order persistence, and rejecting raw reasoning events.
- `node scripts/verify-native-stream-fixture.mjs`: six transport/prompt/tool/failure scenarios passed.
- Real DeepSeek run on an isolated copy of the affected saved session: 1,174 input records including the diagnostic; replay reduced from 3,722,485 to 117,645 characters. A checkpoint covers 1,139 original records. The model returned `NEYVIA_CONNECTION_OK` with exact system-prompt validation.
- Installed backend repeated that diagnostic successfully with zero summarization calls and one cache hit. Full original session still has 1,173 records. The checkpoint prefix was independently matched to the original SQLite history before installing it for the real session. Firmware version 0.84.1 and Flipper recovery context remain in the checkpoint.
- Browser component journey used a clearly labeled synthetic trace rendered by production `NeyviaLiveToolTrace`: expanded default, summary/tool/summary/tool order, compact mode, reload persistence, expansion restoring order. This is a production-component journey, not a live-provider browser end-to-end test. Temporary fixture files were removed.
- Native installed application was visually inspected after restart: 89 saved chats, RentSecurity workspace, Full access, DeepSeek V4.1 Flash. Private backend health passed.

Proof receipts: `proof/session-compaction-20260928/`. The local NSIS installer is `src-tauri/target/release/bundle/nsis/Neyvia_0.1.0_x64-setup.exe`. Tauri changes its embedded bundle marker from UNK to NSS when packaging, so installed executable verification accounts for exactly that marker difference. No public NAS release was changed.
