# Live tools and local artifacts — 25 September 2026

This checkpoint follows the prompt and streaming repair. It addresses the user's
request to see actual tool activity and verify that a model can create an artifact
and use browser/computer tools from Neyvia.

## Gaps found and repaired

- Live tool events carried labels but omitted inputs and results. Events now carry
  stable call identities and bounded, credential-redacted details. Native gateway
  calls display the underlying tool name. Failures remain failures.
- Long answer streams displaced tool activity from bounded run receipts. Token
  frames no longer crowd out saved calls; a turn's receipt contains its own calls.
- Tool cards, provider thinking summaries, and reconnect notices now remain
  available during replies and in saved conversations. No reasoning is invented.
- Native had no generic text-file writer, and ordinary chat was always read-only.
  `workspace.write` now creates UTF-8 files, reads them back, and returns SHA-256
  plus independently checked operation evidence. Updates require the previous
  hash. The composer exposes a conversation/workspace-scoped permission choice.
- Local permission is limited to the named workspace, preview, and Laya tools.
  It does not grant arbitrary managed-tool or compiled external mutations.
- Windows MCP input inherited the system code page. The real stdio journey
  caught corrupted Unicode; the server now explicitly reads and writes UTF-8.
- The installed journey found two gaps missed by the initial build checks:
  permission state was read before its React hook was initialized, and the
  chat-to-screen projection dropped both thinking summaries and tool details.
  The hook is ordered correctly and shared trace projection now survives those
  mappings, including receipt-based restoration.
- A tool returning JSON text with `ok: false` previously appeared completed.
  The event adapter now parses explicit failure results; the real protocol
  fixture verifies a missing-file failure reaches both the provider and stream.
- The first live DeepSeek trial created and read a real HTML file, then exposed
  a Windows extended-path containment mismatch during Preview. Its failed run
  is retained as evidence; it is not counted as a successful Laya journey.
- Windows Preview containment now compares canonical resolved paths. A real
  stdio-MCP call with an extended workspace root and ordinary output path passed
  the Laya click postcondition and checked screenshot/report hashes. An outside
  output directory was rejected without creation. Preview's generic operation
  status stays `unverified` because that layer has no Preview adapter; the Laya
  receipt separately proves its executed browser actions.

## Verification boundaries

Evidence is stored under `proof/tool-journey-20260925`. The controlled protocol
checks are distinct from live provider and installed UI observations. The local
HTML trial uses a disposable file and a loopback page, with an explicit button
postcondition. Only receipts actually produced by a completed trial count.

Laya currently advertises `calculator_2_plus_3` and
`neyvia_desktop_navigation`; `generic_native_app_coverage` is false. A browser
journey or Neyvia navigation does not prove control of arbitrary desktop apps,
phones, remote PCs, or a NAS. File creation does not prove packaging/installing a
complete generated application. This checkpoint makes no universal best-harness
or model-quality claim.

## Installed and live result

- `live-verification.json`: actual installed Tauri composer, Neyvia Native,
  OpenCode Go / DeepSeek V4.1 Flash, High reasoning. The task completed in
  55.28 s, with live provider thinking and live tool cards. The model recovered
  from one invalid write invocation before creating the requested new file.
- `final-created-by-deepseek.html`: 1,598 bytes; independently matched the write
  and readback SHA-256 `3fb38983a8910009f42aa1b5878fe654faa7cfe0802c5082c6d444b5fc1a4ae6`.
- `live-laya-browser-report.json`: Laya actually executed the button click and
  independently passed `#result = Verified by Laya`; 6,504.755 ms including its
  capture path. The taste report found no blocking findings, warnings, or notes.
  These measurements are not a beauty benchmark or a provider speed comparison.
- `history-restored.json`: after reloading the installed WebView, all 11 tool
  cards and the provider thinking summary remained. The transient tool grant
  returned to read-only.
- `installed-readonly.json`: a separate run with the permission still read-only
  showed its denied write as **Failed**, streamed thinking/tool activity, and
  created no target file. The model requested a grant instead of claiming success.
- `live-laya-native-receipt.json`: DeepSeek called capabilities and the actual
  `neyvia_desktop_navigation` workflow. Laya bound installed PID 54788, verified
  four transitions, returned to chat, and reported no unknown outcome. The
  Native call took 4,896 ms; the whole model task took 34.435 s. The independently
  read receipt hash matched the tool result. This is only the named Neyvia journey.
- 126 frontend checks passed; the real stdio workspace protocol covered UTF-8,
  create/readback, hash-guarded update, replay suppression, read-only/outside-path
  denial, and preservation of the original validation error. Controlled provider
  protocol checks covered Responses and Chat Completions partial output, matching
  tool identities/results, a failed JSON tool result, and a provider error.

The final backend-only packaging pass preserves the specific validation error
instead of a generic failure message. Final installer identity, matching installed
source hashes, user-setting restoration, and the NAS checkpoint are recorded in
the associated proof files. The installer is local WIP, not a published release.

Final installed SHA-256:
`3d2a2384fcc031ef07397ea9157b25a9f7271fe0da8d44fd9b86ad464bef337f`.
All nine checked backend modules match their installed copies. After a normal
restart, Laya reverified four desktop transitions against final PID 18300 in
3,657.768 ms. The diagnostic port is closed. RentSecurity, DeepSeek, Model default
reasoning, and read-only permission are restored; the saved prompt file hash is
unchanged. The loopback and Tailscale health routes return HTTP 200.
