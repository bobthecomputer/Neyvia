# Runtime completion — 25 September 2026

**Superseded timeout policy:** the later request "No budget" removes the default
chat duration limit. See [the correction](neyvia-no-run-budget-20260925.md). The
finite deadline values below describe the earlier checkpoint, not the current
chat default.

## Requested outcome

Long-running tasks must survive the desktop bridge; prompt overrides must be
independent for each runtime/model; users must be able to discover real tools,
skills and integrations, and browse the provider/model choices supported by
OpenCode. Saved prompts, existing work and exact route selection must survive.

## Acceptance checks

- A desktop request lasting more than 180 seconds completes with its real result.
- Errors remain visible; request deadlines are finite and independent of reasoning effort.
- Two runtime/model prompt overrides persist independently, resolve on dispatch,
  and can inherit the existing global prompt without changing it.
- The installed prompt editor imports text/Markdown into the selected scope.
- A searchable capability view reports actual installed tools, skills and plugin
  availability, and inserts a usable request into the composer.
- Provider browsing uses a real catalog, preserves exact provider/model IDs and
  distinguishes configured routes from those needing connection setup.
- The installed app and authenticated responsive controller use the new build.

## Observed starting failure

`call_desktop_backend_command` awaited every Python bridge request with a fixed
180-second timeout and `kill_on_drop(true)`. Chat dispatch waits for the entire
agent run. A second budget in `web_backend.py` assigned 120–900 seconds according
to reasoning effort. The interrupted turn's stream contained real tool activity
but no final completion event. Its actions are not replayed automatically.

## Changes

- The desktop bridge now derives its deadline from the task budget. Chat defaults
  to 3,600 seconds, accepts an explicit budget up to 7,200 seconds, and gives the
  runtime time to finish cleanup. Reasoning effort does not change task duration.
  Short state queries retain short deadlines. A real timeout kills and reaps the
  Windows process tree; uncertain cleanup is reported explicitly.
- Prompt resolution is exact route, model, provider, runtime, then global. Each
  override is a complete system prompt. The editor exposes these scopes, supports
  text and Markdown imports, and can remove an override to inherit again. Revision
  checks prevent concurrent edits from silently overwriting one another.
- Native and Codex dispatch resolve the selected scope. OpenCode receives its
  override through an agent system-prompt file reference, preserving long prompts
  without placing their text in Windows environment variables or user messages.
  Claude Code now receives the same scope through `--system-prompt-file`, using
  the existing external CLI event bridge and preserving its permission settings.
- The composer exposes **Tools & integrations** under its plus button. It lists
  the actual Native tool catalog, deferred input schemas, skills, MCP connection
  state and Codex plugin metadata. Selecting a tool adds a draft request.
- **Browse all providers and models** opens a cached Models.dev/OpenCode catalog.
  Selection sets the runtime, provider and model together. OpenCode routes retain
  exact IDs, including nested model names; legacy aliases no longer rewrite them.
  API-key setup remains in the desktop, merges the existing OpenCode auth store,
  and requires an explicit replacement choice for existing credentials.
- The installed-app check caught two additional failures: a Rust catalog handler
  called a nonexistent CLI command, and a 4.17 MB catalog response could not return
  through the controller's 2 MiB request pipe. Catalog handlers now use the real
  Python registries. Only completion envelopes get a larger bounded input limit;
  ordinary requests remain limited to 2 MiB. Delivery errors are returned as small
  failures so the remote UI does not wait silently.

## Verification

- Real PowerShell child returned its exact result after 181.48 seconds through
  the production Rust wait helper. Budget selection, timed-out process cleanup,
  and controller SQLite expiry checks also passed.
- Scoped prompt verifier: 11 checks passed, including independent routes,
  imports, inheritance, and a real two-process revision conflict.
- Runtime dispatch verifier: 10 checks passed, including OpenCode system-channel
  configuration, exact provider IDs and reasoning-independent time budgets.
- Claude prompt-file verifier: the file path is forwarded, authored content is
  absent from argv, read-only policy remains intact, and other runtimes reject
  accidental use of the Claude-specific option. This checks the installed CLI
  contract and generated invocation; no live Claude provider call was made.
- Targeted streaming, route, provider and inventory tests: 24 passed. Native
  streaming fixtures exercised both provider protocols, early deltas, real tool
  results, and visible provider/tool failures. These are fixture runs, not live
  provider speed measurements.
- The first full build installed successfully: 13 Python module hashes and the
  packaged executable matched the build. LAYA's installed desktop journey passed
  all four transitions (Chat → Library → Chat → Settings → Chat), in 4.61 seconds
  at the gateway, without moving the physical cursor or bringing Neyvia forward.
- Through the authenticated desktop controller, Markdown import → save override
  → close/reopen retained the exact test prompt. Text import worked too. Removing
  the test override restored inheritance. The user's 40,355-character global
  prompt retained its exact content hash; revisions advanced from 10 to 12.
- The phone prompt dialog was inspected at 390 × 844, with no horizontal overflow.
  Phone provider filters initially overlapped and the refresh label was clipped;
  filters now wrap, the refresh icon has a 40-pixel button, and the corrected
  layout was inspected before packaging.
- The controller now returns all 223 providers and 8,179 models. Selecting
  DeepSeek V4.1 Flash on OpenCode Go sets `opencode / opencode-go /
  deepseek-v4.1-flash`, survives reload, and exposes that exact prompt scope.
- The tools panel loads 115 registered tools, 20 skill rows, and 29 connection
  rows. Selecting `terminal.exec` inserted a request into the composer without
  executing it. Input schema inspection exposed another IPC argument mismatch;
  both catalog commands now use the common Python command envelope. Switching
  tabs clears the previous search so it cannot silently hide the new list.

Evidence is kept in `proof/runtime-completion-20260925/` and the existing desktop
deadline proof directory. Source changes are local WIP until a separate release
decision.

### Final installed checkpoint

The final NSIS build installed and reopened successfully. All 14 checked Python
modules and the packaged executable match the final build; the saved user prompt
was preserved. LAYA passed all four installed navigation transitions in 3.70
seconds on process 11768, with no physical cursor movement. The responsive
controller then retrieved the real `terminal.exec` schema from that installed
app, including PowerShell/Python/Bash/Cmd choices. Switching from OpenCode to
Neyvia Native preserved DeepSeek V4.1 Flash on OpenCode Go. Selecting the tool
inserted its request; the disposable draft was cleared without running it.

## Boundaries

- Catalog availability is not provider health. The observed catalog has 223
  providers and 8,179 models; each route still needs valid access and a compatible
  configured endpoint. Broad catalog selections use OpenCode.
- Codex plugin entries are metadata unless explicitly connected. This work does
  not claim native execution of every Codex or Hermes plugin.
- Hermes v0.21.3's installed CLI exposes no system-prompt replacement flag. Its
  SDK's `ephemeral_system_prompt` adds to its base prompt. Hermes and the other
  CLI adapters without a replacement mechanism still receive saved instructions
  as task context; the editor states this limit. They are not presented as full
  system-prompt replacement.
- LAYA proves the named installed desktop navigation journey only. Dialog checks
  use the responsive browser controller, executing commands in the installed app.
- The interrupted user task was not replayed. It had already performed actions,
  so retrying it automatically could duplicate those actions.
- Tailscale's existing private 8443 route still targets port 47881. The independent
  service on 443 remains unchanged. No public release was promoted.

## Adapter references

- [Claude Code CLI](https://code.claude.com/docs/en/cli-usage), checked against the
  locally installed help for system-prompt options.
- [Hermes Python library](https://hermes-agent.nousresearch.com/docs/guides/python-library),
  checked against installed v0.21.3 source for additive system instructions.

## Main implementation files

- `src-tauri/src/lib.rs`: subprocess deadline/cleanup and catalog IPC handlers.
- `src/grant_agent/{desktop_bridge,desktop_controller,web_backend}.py`: desktop
  dispatch, bounded remote completions, route handling and prompt delivery.
- `src/grant_agent/{agent_prompt_library,provider_catalog,runtime_capability_inventory}.py`:
  scoped storage and live inventories.
- `src/grant_agent/{neyvia_agent,opencode_bridge,external_cli_bridge}.py`: runtime
  system-prompt channels.
- `web/src/neyvia/{NeyviaShell,NeyviaWorkspace,NeyviaPromptEditorDialog,NeyviaRuntimeCapabilities,NeyviaProviderBrowser}.jsx`:
  composer entry points, dialogs and connected actions.
