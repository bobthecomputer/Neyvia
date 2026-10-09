# Neyvia native runtime and tool contract

## Honest architecture

Neyvia owns the deterministic harness, planning and verification loop, action policy, receipts, mission state, tool selection, and proof gates. Hermes, OpenClaw, OpenCode, Cursor Agent, and provider APIs remain pluggable model or delegated execution runtimes.

The native layer is therefore a tool runtime and controller, not a fake model provider.

## Upstream capability audit

The July 12, 2026 audit used current primary documentation:

- OpenClaw tools and policy: <https://docs.openclaw.ai/tools>
- OpenClaw progressive Tool Search: <https://docs.openclaw.ai/tools/tool-search>
- OpenClaw browser screenshots: <https://docs.openclaw.ai/cli/browser>
- Hermes tools and toolsets: <https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/>
- Hermes progressive Tool Search: <https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-search>
- Hermes web providers: <https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search>
- Hermes deliverable mode: <https://hermes-agent.nousresearch.com/docs/user-guide/features/deliverable-mode>
- OpenCode tools and permissions: <https://opencode.ai/docs/tools/>

The useful shared pattern is:

1. expose a small core tool set directly
2. search compact tool descriptors for the long tail
3. load one exact schema only when needed
4. enforce policy on the underlying tool
5. record a typed result and proof artifact

## Neyvia native tools

`NativeToolRegistry` implements compact search, exact description, typed calls,
availability checks, and `fluxio.native_tool_receipt.v1` receipts. Catalog and
tool descriptions now advertise protocol version `1.1`, mutability,
capabilities, parallel-safety, and JSON Schema-like argument contracts. Calls
are rejected before execution when a required argument is missing, has the
wrong type, falls outside its bounds, or violates an enum.

The protocol is deliberately data, not a new programming language:

```text
search -> describe -> validate -> authorize -> call -> receipt
```

This keeps native tools compatible with MCP-style discovery while allowing
Neyvia to enforce stricter local policy and proof rules.

Initial executable catalog:

- `workspace.search`
- `context.search`
- `context.bundle`
- `context.compact`
- `orchestration.compile`
- `codex.assets.inspect`
- `codex.assets.import`
- `web.search`
- `web.fetch`
- `preview.inspect`
- `preview.screenshot`
- `video.inspect`
- `video.digest`
- `nas.file.send`
- `nas.message.send`
- `nas.message.receive`

The hybrid action executor recognizes explicit search, preview, screenshot, and NAS intents before general runtime delegation. A failed tool remains failed and writes an error receipt. It cannot be converted into narrative success.

## Search contract

Search and retrieval are separate tools.

`web.search` selects the first configured path:

1. SearXNG via `NEYVIA_SEARXNG_URL` or `FLUXIO_SEARXNG_URL`
2. Brave via `BRAVE_SEARCH_API_KEY`
3. no-key DuckDuckGo HTML fallback

The result always names the provider. An empty parsed result is a failure, not a completed search.

`web.fetch` accepts only HTTP or HTTPS and returns the final URL, status, content type, title, readable bounded text, and truncation state.

## Preview and screenshot contract

Preview is no longer only a UI surface.

- `preview.inspect` proves HTTP reachability and extracts the returned document title and readable text.
- `preview.screenshot` waits for network idle, an optional readiness selector, or a bounded delay. It uses Playwright when available and Chromium headless as a fallback.
- A successful screenshot returns a real PNG path, engine, width, height, file size, and SHA-256 hash.

## Video evidence contract

GPT-5.6 Sol accepts image input but does not accept video input. Neyvia therefore
converts video into timecoded evidence that an image-capable model can inspect.
The current contract is documented at
<https://developers.openai.com/api/docs/models/gpt-5.6-sol>.

`video.inspect` uses FFprobe and returns:

- source SHA-256 and byte size
- duration and timecode
- container, video codec, dimensions, frame rate, and frame count
- audio stream presence, codecs, and sample rates

`video.digest` uses FFmpeg and returns:

- evenly sampled timestamped JPEG frames with brightness, contrast, and frame
  delta measurements
- a filtered selection that rejects blank and near-duplicate samples
- scene-change JPEG frames using FFmpeg scene scores
- one tiled storyboard built only from selected useful frames
- a `video-digest.json` timeline mapping images to timestamps
- 16 kHz mono WAV audio when an audio stream exists
- a local Whisper JSON transcript when Whisper is already installed

Whisper is optional and is never silently installed. If it is unavailable, the
digest remains successful and preserves the extracted WAV for another speech
provider. This avoids turning transcription availability into a false video
analysis failure.

FFmpeg documents `select`, `scdet`, representative `thumbnail` selection, and
the `tile` storyboard filter at <https://ffmpeg.org/ffmpeg-filters.html>.
PySceneDetect remains a compatible future enhancement for advanced cut
detection: <https://github.com/Breakthrough/PySceneDetect>. Local Whisper is
documented at <https://github.com/openai/whisper>.

Example:

```powershell
python -m grant_agent.cli native-tool-call --root . --tool video.digest `
  --arguments-json '{"path":"demo.mp4","maxFrames":12,"maxSceneFrames":8,"transcribe":"auto"}'
```

## NAS exchange contract

The NAS bridge stores attachment payloads by SHA-256 and sends small atomic JSON message envelopes that reference them.

Properties:

- an interrupted `.partial` transfer resumes from the existing byte offset
- the destination checksum is verified before publication
- repeated content is reused without retransmission
- multiple message attachments upload in parallel
- inbox and outbox envelopes are written atomically
- receive materializes and verifies attachments locally
- optional acknowledgements are durable files

The bridge uses an existing mounted NAS or SMB path. It does not require a second daemon or expose credentials in messages. Rclone, rsync, or an MCP transport can be added behind the same protocol later.

### Measured mounted-share proof

Test payload: `5,167,616` bytes.

- first send: `203 ms`, `203.02 Mbps`, checksum verified
- second send: `0` bytes transferred, `5,167,616` bytes reused
- receive: two envelopes read, attachment materialized, SHA-256 matched

The measured route was the mounted project share at `Y:/projects/vibe-coding-platform`.

## Final live verification

- native catalog: `16/16` tools available, with schemas deferred until an
  exact `describe` call
- no-key web search: DuckDuckGo HTML returned the current OpenClaw Tool Search documentation in `723 ms`
- screenshot: Playwright captured the live Neyvia control surface at `1440 x 1112`
- screenshot SHA-256: `91e9413b76f851ca4cb74f4050906ca2b6fd58b07a4d60581fdaf8a3931e9086`
- interactive browser probe: the embedded preview received a real primary-action click and reported it to the parent surface
- browser console: no errors during the Agent to Browser to Agent interaction path
- video digest: a real Neyvia Agent, tutorial, and Builder workflow produced 12
  samples, rejected blank and near-duplicate frames, and selected seven useful
  timecoded frames for the storyboard
- real workflow proof:
  `.agent_control/mission_artifacts/native_tools/video/neyvia-real-ui-20260712T195258Z`
- real storyboard SHA-256:
  `aecbd6df2efce2f073ebf31fa64534dc121ecab381d596d855733ac4a84cc8f9`
- Ultra UI proof: the live mission form accepted product effort `Ultra` with worker effort `High` and reported no browser console errors

## CLI

```powershell
python scripts/run_grant_agent_cli.py native-tools --root . --query screenshot

python scripts/run_grant_agent_cli.py native-tool-call --root . `
  --tool preview.screenshot `
  --arguments-json '{"url":"http://127.0.0.1:1420/control?preview-control=1","waitFor":"main#fluxio-main-content"}'

python scripts/run_grant_agent_cli.py nas-message-send --root . `
  --nas-root Y:\projects\vibe-coding-platform `
  --sender workstation --recipient nas-worker `
  --message "Verify this artifact" --attach .\report.pdf

python scripts/run_grant_agent_cli.py nas-message-receive --root . `
  --nas-root Y:\projects\vibe-coding-platform `
  --recipient workstation --output-dir .\.agent_control\nas_received --acknowledge
```
