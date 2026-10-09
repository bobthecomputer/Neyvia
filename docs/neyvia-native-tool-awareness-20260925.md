# Neyvia Native tool awareness — 25 September 2026

## Observed failure

The user reported that DeepSeek claimed it could not launch commands or inspect connected devices. The affected conversation was `chat-1790331473557-slitbpy`, in the `RentSecurity` workspace.

Its recorded turn used Neyvia Native, OpenCode Go, DeepSeek V4.1 Flash, High effort, and **Full access**. The Native receipt recorded the `terminal.exec` grant, an active function-tool loop, and 11 model-visible tools. The model made zero tool calls and reported no execution error. The lack-of-tools claim was unsupported; it was not evidence of a failed USB connection or missing command executor.

## Change

- Make the current permission mode, selected workspace, and available command interpreters visible in the tool descriptions provided with the model request.
- Expose a direct command tool through the existing SDK and MCP gateways. It uses the same executor, permission checks, action IDs, and receipts as `terminal.exec`.
- Keep environment discovery available in Read-only mode, and distinguish it from permission to run arbitrary commands.
- Preserve the authored system prompt. Do not force a tool call or change provider/model selection.
- Keep command activity labeled as `terminal.exec` so existing live icons, inputs, outputs, and failure states remain usable.

## Verification

Evidence is under `proof/native-tool-awareness-20260925/`. `baseline.json` and `failing-turn-metadata.json` record the observed configuration without copying the system prompt or complete private transcript.

- `node scripts/verify-native-capability-discovery.mjs` passed 12 checks against the production SDK and MCP wrappers: current capability metadata, unchanged custom prompt, benign command execution, and Read-only rejection.
- `node scripts/verify-native-command-access.mjs` passed the existing permission, explicit Read-only override, idempotent replay, and nonzero exit checks.
- Eight existing chat-stream checks passed, including real stream polling and tool input/output/failure preservation.

- The backend-only installer was built and installed. `installation.json` confirms 11 installed modules match source, the desktop executable is unchanged from the verified controller build, the saved system prompt hash is unchanged, and no diagnostic browser port was requested.
- `live-awareness.json` and `verified-live.json` record the actual same-session UI journey through the Tailscale controller into the installed app: DeepSeek received 12 tools and used `neyvia_terminal_exec`. The first call mistakenly quoted the entire script and printed it; the model corrected the second call and executed the diagnostic. Both calls and their real output remained visible, with tool icons and streamed activity.
- The successful PowerShell output reported ASUSPSDLB, `C:\Users\example\Projects\RentSecurity`, PowerShell 7.6.5, 18 present USB-class PnP entries, COM4, and WSL availability. `independent-host-check.json` confirmed the host/device metadata separately. USB-class entries include infrastructure such as controllers and hubs; this does not identify an attached card reader.
- The original conversation remains open in the installed app. Its prior Full access selection was restored for the same `RentSecurity` scope after restarting; its composer is empty and DeepSeek remains selected.
- `laya-installed.json` records a bounded native navigation attempt refused by `desktop_action_activated_neyvia`. It performed zero actions and is not counted as passed. The real command journey and installed UI were verified separately.

## Scope

Command execution and device enumeration are distinct from a successful connection to a particular reader. A successful benign command does not establish that any Proxmark, Flipper, badge, or RF operation is available or was performed. No card content or device state is changed by this verification.

Clearer tool exposure cannot guarantee that a provider model will choose to use a tool for every request. The original model also separately declined the requested badge operation; exposing an existing command executor does not change the provider's policies.

Publication note: local account paths and network identifiers in this document are neutral examples.
