# Harness action checks — 2026-09-27

The composer exposes saved permission modes for Native, Codex CLI, Claude Code and Hermes. The dispatcher previously forced every external runtime to read-only. Explicit full access now reaches Codex's host access mode, Claude's bypassPermissions with its default tools, and Hermes's --yolo. Codex workspace mode retains workspace-write; Claude workspace mode exposes editing without Bash. Hermes has no implemented workspace-only mode, so the UI offers read-only and full access, and the backend reports a requested workspace mode as unsupported/read-only. Other harnesses retain their prior behavior.

Native's Codex subscription adapter also previously mapped full access to workspace-write. Both its CLI and app-server paths now retain the selected mode. The live action run below exercised the CLI transport. Native's MCP still independently enforces tool grants for narrower modes.

## Observed model journeys

`node scripts/verify-harness-actions-live.mjs [native|codex|claude-code|hermes]` creates an isolated fixture folder. Models receive a benign action request, not any supplied private system prompt. Each action has a file postcondition checked independently by Node.

| Harness/model | WSL Ubuntu 24.04 | Local npm installation | Chromium launch and click |
| --- | --- | --- | --- |
| Native / gpt-6-luna / Codex CLI transport | Passed | Passed | Passed |
| Codex CLI / gpt-6-luna | Passed | Passed | Passed |
| Claude Code / sonnet | Blocked before inference | Blocked | Blocked |
| Hermes / gpt-6-luna / openai-codex | Missing Hermes Codex credentials | Blocked | Blocked |
| Hermes / anthropic/claude-opus-4.6 / OpenRouter | HTTP 402 insufficient credits | Blocked | Blocked |

Claude's own session log recorded repeated ECONNREFUSED and a final connection error. The adapter initially failed earlier because system_prompt_file was passed to the process runner as an unsupported keyword; this was corrected while preserving the CLI argument. The remaining failure is the configured provider endpoint. Hermes's OpenRouter attempt used the existing same-provider credential in process memory only; it was not persisted in the fixture or exported in evidence.

Installation means installing and requiring an authored local npm package with lifecycle scripts disabled. Browser proof means shell-launched headless Chromium against a disposable local HTTP page, followed by a real button click and cleanup. It does not establish arbitrary GUI control, administrative installers, universal plugins, or Native workspace.browser support for arbitrary origins. The latter remains limited to its existing approved local routes.

## Checks and delivery

The production argument builder check and seven permission persistence/selector checks pass. Actual Native stdio MCP checks verify read-only and workspace command denials, full-access command execution, duplicate suppression, and nonzero-exit reporting. Browser UI inspection verified Full access remains visible when switching through Codex, Claude and Hermes, with Hermes's unsupported workspace option absent.

Skill import checks and the browser import journey are documented in `neyvia-skill-import-20260927.md`. Source and proof are local WIP; executable and NSIS installer are local build artifacts, not an installed or public update. Build hashes and scope are in `proof/skill-import-20260927/build-receipt.json`.
