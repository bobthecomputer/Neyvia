# Native access to Codex instructions and plugins — 2026-09-27

Native now exposes `codex.instructions.list`, `codex.instructions.read`, and `codex.prompts.read`. Enabled personal, project, and plugin skills are read on demand with hashes; disabled plugins and references outside a skill are rejected. Authored system prompts are unchanged.

`codex.plugins.list/search/describe/read/call` discovers enabled local Codex MCP definitions and invokes their actual servers with JSONL framing. Tool enable/disable filters and Native write permissions apply. Remote OAuth and app-host connectors remain unsupported, with visible reasons. Configuration and credentials are not copied into the catalog.

Skills picker includes Codex instructions. Selecting one inserts its stable ID and read-tool guidance into the composer. Fresh local browser journey showed 123 Native tools, 214 skill entries (including existing Neyvia entries and disabled Codex entries), and successful selection of better-writing. This is local source/build verification, not a desktop installer release.

Verification: Node-driven Native gateway fixture loads actual instruction bytes and executes a disposable Node MCP server, blocks read-only writes and disabled tools. JSONL transport fixture covers initialize/list/call/error/timeout/reaping. Existing six Native model-protocol scenarios pass, frontend build passes (existing large-chunk warning), inventory secret-exclusion test passes.

Installed node_repl: real tools/list succeeded with js, js_add_node_module_dir, js_reset, turn_ended. Actual js invocation returned remote_tool_error: Windows sandbox helper setup refresh failed outside the Codex host. Receipt: proof/native-codex-access-20260927/installed-node-repl.json. Thus universal plugin parity is NOT achieved. Host transport/session integration and remote OAuth support remain necessary; no provider or model substitution was used.
