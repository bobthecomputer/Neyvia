# Connected composer and Claude approvals

Scope: Neyvia-next, branch night/neyvia. The public Neyvia release is unchanged.

The next composer has a + menu for image attachments and manual Neyvia tool calls. Images can be picked, pasted, dropped, previewed and removed. Supported routes accept image-only sends; unsupported routes explain the limitation. Claude terminal mode still cannot accept images through Neyvia. Switching to Agent SDK credit requires the person's click. Existing model, effort, permission and transport selections remain in the submitted options.

Image drafts remain in memory, scoped to their originating chat. Failed sends preserve them; successful sends remove only the images actually sent. Metadata admission rejects unsupported, oversized and excess files before decoding, followed by actual-byte validation. Exact retries reuse their request ID; changed images or options get a different identity.

Manual tools reuse the existing native catalog, schema and execution commands. The browser runner uses the selected chat folder for native calls and shows availability, read/write class, arguments and receipts. Neyvia workspace/PDF actions use the existing UI bus and its approval flow. Nothing executes until Run; mutations require explicit confirmation. The desktop bridge still restricts native tools and forces its own state folder; the UI describes that difference. Provider-owned built-in tools remain model-operated.

## Folder-trust contract

Claude terminal startup no longer refuses an untrusted folder before launching the official CLI. It recognizes the installed CLI's specific startup trust menu and emits the existing connected approval card:

`pendingRequest {requestId,kind:"approval",category:"folder_trust",title,detail,cwd,choices:["approve","deny"]}`

The card includes the actual dialog wording and the launch folder. No key is sent until the owner answers. The response selects the matching native menu entry, accounting for its actual order and selection. Unknown, changed or closed menus fail closed. Stop cancels; Deny chooses exit and stops. Startup timeout is suspended while awaiting the existing bounded approval timeout and reset after answering. Trust is recorded by Claude Code; Neyvia does not edit its trust flags. Existing hook-based tool approvals and questions keep their route.

This parser is deliberately narrow: a future Claude CLI wording change may need an update. Login and other unsupported interactive prompts still require the existing external handoff. The actual installed version observed was Claude Code 2.1.286.

## Ignored Codex setting

Installed codex-cli 0.159.3 does not recognize `computer_use.windows.always_allowed_app_ids`. Its [version-pinned OSS schema](https://raw.githubusercontent.com/openai/codex/rust-v0.159.3/codex-rs/core/config.schema.json) contains only `aumids` and `exes` in that Windows block. Converting the ignored table into a list would still be unsupported by this installed version.

The original global config was preserved in `C:\Users\example\.codex\config-recovery\20261001-155108-computer-use.toml`. The ignored block is now comments in config.toml; all remaining parsed settings were checked identical. No replacement permission was granted. An actual installed Codex app-server initialized without this warning; no model turn was submitted. Recovery files are outside source control and excluded from the NAS source snapshot.

## Evidence and remaining gates

- `node docs/verification/connected-trust.mjs`: 16 checks, including no automatic input, native menu ordering, stale/replayed answers, cancellation, startup deadlines and exact options.
- `node docs/verification/connected-images.mjs`: 8 checks through the real broker with a deterministic adapter; new/continued image-only sends, unchanged image/options payloads, replay deduplication and empty-send refusal.
- `node docs/verification/connected-controls-http.mjs`: 6 authenticated/anonymous contract checks against 47891; 145-tool catalog, schema, manual file read, workspace escape refusal and image-only validation. No model invocation.
- `node --test web/src/neyvia/next/*.test.js`: 15 passed. Frontend production build passed in a scratch output directory, with fixtures excluded.
- The actual official Claude terminal produced a folder-trust card in a disposable folder. Deny returned interrupted, the folder remained untrusted and UserPromptSubmit never fired. Receipt: `.sandbox-scratch/night/connected-trust-native.json`.
- Claude worker reported 28 headless fixture UI checks and screenshots in `.sandbox-scratch/connected-ui/`. A1 inspected the saved + menu and trust-card screenshots. These demonstrate fixtures, not a live backend journey. The worker used installed Playwright in its initial pass despite the unavailable Chrome route; the follow-up explicitly prohibited further browser automation and performed none.
- CUA inventory returned no browsers/apps. A joined real-browser journey and the desktop app remain unverified. Native trust Approve is covered with a deterministic terminal, but was not clicked in the real CLI: the person's trust decision remains theirs.

No feature removal, dependency installation, live restart, public promotion or automatic credit-route switch was performed. All A1 verification calls used zero provider turns. One Claude frontend worker plus one focused continuation produced the frontend changes; those implementation calls are separate from verification usage.

Publication note: local account paths and network identifiers in this document are neutral examples.
