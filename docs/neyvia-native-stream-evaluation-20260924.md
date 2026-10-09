# Neyvia native chat streaming: evaluation handoff (2026-09-24)

## Goal and implemented path

A short GPT-6 Luna message in the installed Neyvia desktop previously took about 35 seconds with no visible thinking or answer until completion. The native `neyvia-agent` route now calls the Codex app-server streaming transport, writes provider events to a per-turn JSONL stream, exposes cursor-based reads through the desktop/backend command bridge, and updates the pending assistant bubble with answer deltas and reasoning summaries. A read-only greeting skips the slow mission mirror, and the chat supervisor no longer instructs a standalone greeting to read saved task state. The desktop bridge emits ASCII JSON bytes and replaces malformed provider surrogate characters so Tauri's JSON parser accepts a completed answer. The operator can select GPT-6 Luna with its supported reasoning levels. The OpenCode Go picker again offers DeepSeek V4.1 Flash.

The first model/route choice made while workspace data is loading now survives hydration. This was an actual bug: Neyvia Native could silently revert to Hermes, then the model choice could switch the route to Codex.

The installed desktop exposed another race: New Chat took several seconds to create its durable conversation, but the composer could send immediately. The model answer completed and saved, then late creation replaced the visible selection with an empty chat. New Chat now holds the composer read only and blocks Run until creation finishes. A delayed browser test and the installed desktop both exercised this state.

The NSIS desktop installer now stages the Python backend, static configuration, and runtime requirements. The installed executable prefers its bundled backend. The final unsigned local setup is `src-tauri/target/release/bundle/nsis/Neyvia_0.1.0_x64-setup.exe` (13,473,097 bytes; SHA-256 `952FB73F4A01E32B9FF01595CC0B066BA7B129BA4DEA90CA49EEE3D74D9F780C`). It has been installed at `C:\Users\example\AppData\Local\Neyvia\neyvia-desktop.exe`; `proof/native-stream-20260924/final-install-receipt.json` confirms the hashes of three existing local state files were unchanged. The built installer passes the 14 MiB budget.

## Observed proof

- `proof/native-stream-20260924/installed-bridge-check.json`: installed bridge, real GPT-6 Luna via `codex-app-server`, completed in 15.6 s; first progress at 0.8 s, first answer at 14.1 s, eight answer chunks, one reasoning summary. This is a single run, not a latency guarantee.
- `proof/native-stream-20260924/installed-desktop-ui-stream.json`: an actual installed desktop New Chat, Neyvia Native / GPT-6 Luna / Low, blocked Send during creation and made the draft read only. The pending indicator appeared at 0.28 s, the thinking summary at 15.62 s, and the answer at 15.63 s, before backend completion at 16.85 s and visible completion at 17.22 s. The reply included an emoji; no runtime error appeared. Its stream had 13 answer chunks and one summary. These are one-run timings, not latency guarantees.
- `proof/native-stream-20260924/installed-go-check.json`: the final installed bridge also completed a real OpenCode Go / DeepSeek V4.1 Flash greeting in 14.8 s with the requested model and a nonempty reply.
- `proof/native-stream-20260924/ui-stream-check.json`: running browser UI on the updated local backend, Neyvia Native + GPT-6 Luna + Low stayed selected. A thinking summary appeared at 14.42 s and partial answer at 14.45 s before completion at 18.78 s. The verifier checked the visible pending answer itself.
- `proof/native-stream-20260924/new-chat-pending-check.json` and `new-chat-send-check.json`: the delayed browser creation keeps Run disabled, then the subsequent real Luna reply stays on the newly selected conversation.
- `proof/native-stream-20260924/installed-desktop-navigation.json`: UI Automation against the installed desktop opened the system prompt editor, Settings, Updates, and returned to Agent.
- `proof/native-stream-20260924/laya-desktop-navigation-final-installed-receipt.json`: L-A-Y-A's background native workflow independently verified four transitions on the final installed build in 3.85 s without foregrounding Neyvia. The named workflow now recognizes both an empty Agent chat and an Agent chat with a completed conversation. The first final-build run failed closed on the missing active-chat marker; this was fixed and rerun.
- The targeted frontend tests passed 23/23; frontend build and installer size gate passed. The mobile 390 px and desktop portal journey passed without horizontal overflow; the affected native, Go, and phone UI route selectors were exercised.

## Limits to check next

The `127.0.0.1:47880` phone-facing Python backend still runs the older code. Automatic approval review rejected the stop/restart action, so the installed desktop and the separate local test backend have the new backend while the phone-facing service has not been restarted. The static frontend files are rebuilt, but a physical-phone end-to-end run against that older backend is not proven here. Do not claim every app route was verified.

The L-A-Y-A native workflow proves its named Library/Agent/Settings navigation, not arbitrary native chat input or generic computer use. The installed desktop chat was also exercised through UI Automation, with independent stream events checked in the selected workspace's stream log. The app's Library showed an offline-service message when opened, which warrants separate diagnosis. Existing source-side conversation history was not migrated into the installed app's fresh local history store.

The provider emitted one reasoning summary for these greetings. Neyvia shows its pending state immediately and streams provider summary/answer deltas as they arrive; it cannot display reasoning text before the provider emits it. The installed UI proof does not establish a sustained faster-than-competitors claim. Automatic approval review also rejected a WebView remote-debug launch, so the final installed UI was verified through Windows UI Automation and L-A-Y-A rather than remote debugging.

This is a local WIP candidate. It is not signed, published, or promoted to NAS `current`.

Publication note: local account paths and network identifiers in this document are neutral examples.
