# Native command access — 25 September 2026

## User path

Select **Neyvia Native**, then open the permission selector beside the workspace:

- **Read-only**: inspect without executing commands.
- **Workspace tools**: bounded file writes and the existing Preview/Laya actions.
- **Full access**: run PowerShell, Python, or another installed supported shell without repeated local approval prompts. Commands run on this computer and can access its files and network. The selected workspace supplies the default working directory.

The choice applies to the current workspace/conversation and transfers into its first submitted turn. Reloading or changing scope returns to Read-only. The selector works in the desktop and browser for Native; other runtimes retain their own permission mechanisms.

## Implementation

- `src/grant_agent/native_commands.py`: real `terminal.exec`, bounded output, UTF-8, actual exit status, timeouts and process-tree termination; `runtime.environment` reports interpreter and executable paths without dumping environment variables.
- `src/grant_agent/native_tools.py`: searchable command/environment tools, schemas, approval metadata and durable receipts.
- `src/grant_agent/native_access.py`, `neyvia_agent.py`, `neyvia_mcp_stdio.py`, `web_backend.py`: server-derived grants and capability context for SDK and stdio routes. Caller-supplied internal grants do not override the selected mode. Managed connector mutations are not added by these modes.
- The native gateway now uses the selected execution workspace rather than the separate configuration/state root.
- Capability descriptions and the access-context tool expose available powers without appending another persona to the custom system prompt. Existing Windows newline normalization remains in place.
- Access context names the correct tools for commands, runtime discovery, Laya browser journeys and the bounded native navigation workflow. Visual artifacts default to managed workspace paths; tool search explicitly indexes Laya browser checks.
- Native Full access tasks default to a 32-turn ceiling; other modes retain 12. An explicit limit still clamps to 1–64. Exhaustion reports `run_limit_reached` with resume guidance rather than misidentifying a provider failure.
- `NeyviaShell.jsx`, `NeyviaWorkspace.jsx`, `workspaceToolAccess.js/.css`: shared permission state, selector and submission wiring.
- Composer layout gives workspace/access and model controls room at desktop widths. The phone folder label no longer loses its space to button padding. Rendered geometry was checked at 390, 1320 and 1920 CSS pixels rather than relying on a stylesheet parse.
- Model buttons now stay inside their flex/grid cell at all widths, keeping long model names from overlapping the reasoning slider in saved conversations.
- `chat_stream.py`: image bytes remain in the model transport; activity receipts show a short image-payload label instead of encoded image data.

## Verification

- 131 frontend checks passed.
- `verify-native-stream-fixture.mjs`: actual Native CLI against controlled Responses and Chat Completions streams; unchanged custom text apart from LF normalization, partial output, real selected-workspace reads, tool failures and provider failures. A decoy file in the configuration root guards against regression.
- `verify-native-command-access.mjs`: actual stdio MCP denies command execution in Read-only/Workspace, explicit read-only wins over conflicting grants, Full access executes, replay is suppressed and exit 7 stays a failure.
- `verify-native-workspace-write.mjs`: existing file-write/readback/hash/permission protections still pass.
- `verify-native-commands.mjs`: PowerShell Unicode, Python artifact hash, timeout/child cleanup, bounded output and discovery checked by the command-tool worker.
- Release frontend and NSIS installer built successfully. Final installer SHA-256: `554A6B7CB33863739EF55BCD88FA64CC3F9797E4D59AD786432C0E3F335C8667` (13,640,999 bytes). The packaged desktop passes the control-overlap check at 390, 1320 and 1920 pixels.
- Eight changed backend modules hash-match the installed copy. The saved prompt store hash matches this turn's baseline. The executable matches the built binary after the exact expected three-byte Tauri bundle marker change (`UNK` to `NSS`); all other bytes match.
- Local backend was restarted on 47881. Local and existing Tailscale 8443 health endpoints returned 200. Browser permission menu was inspected with real interaction and a screenshot.

Live desktop evidence is saved under `proof/native-execution-20260925/`.

### Adverse first live run

The first installed DeepSeek trial genuinely ran PowerShell and Python, created the two requested files, and read back their hashes. It then spent several calls discovering the correct browser verification route and hit the 12-turn ceiling before running Laya. That whole task **failed**; its command success does not turn it into a passed end-to-end run. The transcript, screenshots and actual command receipt are preserved as `live-command-test.json`, `live-command-test-*.png` and `first-command-receipt.json`.

This exposed the discovery and turn-limit changes described above. A separate final trial uses new output paths so it cannot silently pass by reusing the first trial's artifacts.

### Successful fresh live run

The installed desktop ran **Neyvia Native → DeepSeek V4.1 Flash → High → Full access**. The 142.9-second task completed with live provider thinking, streamed activity, tool icons, and expandable command inputs/results visible.

- PowerShell resolved to `C:\Users\example\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe`.
- Python resolved to `C:\Users\example\Projects\Neyvia\.venv\Scripts\python.exe` (3.12.11).
- PowerShell created the exact 26-byte text artifact. Python created the HTML page and read both files back. Independent Node readback matched both SHA-256 values: text `b934179b581aa112516706e639136f951a803a57fe0266e0063a80b402442320`; HTML `ce6d755d78403a3d67b9861ee366a5c7582fec7097d7815b1a19222d5936300b`.
- `preview.taste` captured desktop and phone renders, then Laya executed the button click and verified `#result` changed to `Verified by Laya`. One visible named control was exercised, with no untested control on this fixture. The screenshots had no blocking measurement finding; that is not a general beauty certification.
- Two ordinary-browser observations failed (no attached browser, then an origin outside that tool's allowlist). Those failures stayed visible; the model recovered using the supported Laya route. This is not a claim that every browser origin is supported.
- Laya's separate named native journey verified four navigation transitions against the earlier installed desktop process in 3.75 seconds. After the final normal relaunch, its background-only runner refused with `desktop_action_activated_neyvia` before taking any action. The final installed app was inspected through its real WebView and Windows accessibility tree; the final native Laya run is **not** counted as passed.

Evidence: `live-command-final.json`, `final-artifact-receipt.json`, `final-laya-browser-report.json`, `final-laya-browser-after-click.jpg`, and `installed-laya-navigation.json`. The total task duration is an observation, not an overhead benchmark or a speed guarantee.

Final package evidence is in `installation.json`, `installed-consistency-final.json`, `composer-layout-installed.json`, `final-open.json`, and `final-installed-laya-navigation.json`. The diagnostic port was removed on normal relaunch. The scoped NAS upload produces `snapshot-plan.json` and `nas-transfer.json`; it preserves the preceding WIP snapshot and does not promote public `current`.

## Boundaries

- Commands have a maximum 120-second timeout and bounded output. This is not an interactive terminal session manager.
- A successful process exit proves execution, not correctness of everything the command attempted. Important artifacts still need readback or behavioral verification.
- Laya's native integration still exposes its named Neyvia navigation workflow; general desktop-app automation is not established by this change.
- Laya's native foreground guard needs clearer readiness reporting: it currently reports a worker verification failure when Neyvia is the foreground process, including during setup. Its browser journey did pass, and the refused native runs performed no actions.
- A new-chat transition can close a dropdown opened while the conversation is still being initialized. The installed verification waited for that transition before selecting the workspace.
- Late CSS injection initially hid a stylesheet-order conflict. The corrected desktop rules use the existing design-system scope, and verification also loads candidate rules before legacy sheets and checks the packaged app.
- This is a local installed build and recoverable NAS WIP, not a promotion of the public `current` release.

Publication note: local account paths and network identifiers in this document are neutral examples.
