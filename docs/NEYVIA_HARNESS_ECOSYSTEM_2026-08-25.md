# Neyvia harness ecosystem audit — 2026-08-25

## Scope and release rule

This inventory covers maintained coding-agent harnesses with a documented CLI, API,
SDK, or durable machine interface. Editor-only assistants, benchmark runners, and
security campaign tools are listed separately so Neyvia never implies that every
agent-shaped project is interchangeable.

A harness is **integrated** only when Neyvia has a real executable adapter, a
truthful transport contract, workspace isolation or permission controls, normalized
receipts, and a test for its command shape. Finding a repository or showing a card is
not integration.

## Canonical Neyvia route

Every orchestration starts from the composer arrow and uses four isolated roles:

1. `context-reader` — Neyvia-native workspace and receipt-bound cache reader.
2. `planner` — Codex with `gpt-5.6-sol`, high effort, read-only.
3. `executor` — the operator-selected harness and model, mutation allowed only in the registered workspace.
4. `verifier` — Codex with `gpt-5.6-sol`, high effort, read-only.

The selected executor is never silently reused as planner or verifier. A missing
provider login remains a visible blocker; OpenRouter is not substituted for a missing
OpenCode Go login.

## Product inventory

| Harness | Neyvia state | Machine surface | Isolation / permissions | Decision |
| --- | --- | --- | --- | --- |
| Neyvia Agent | integrated | native durable loop and receipts | Neyvia policy and workspace grants | First-class |
| Neyvia Hybrid | integrated | runtime-lane orchestration | per-role route and proof boundary | First-class |
| Codex CLI | integrated, installed | JSONL, resume, MCP | native sandbox plus Neyvia workspace boundary | First-class |
| Claude Code | integrated, installed | stream JSON, sessions, MCP | native permission mode plus Neyvia boundary | First-class; official Anthropic auth only |
| Grok Build | integrated, installed | streaming JSON, ACP | tool deny list plus Neyvia boundary | First-class |
| Kimi Code | integrated, installed | stream JSON, ACP | isolated direct-chat mirror | First-class; provider setup is separately proven |
| OpenCode | integrated, installed | structured CLI events | OpenCode permissions plus Neyvia boundary | First-class |
| Cursor Agent | integrated, installed but probe-blocked | CLI structured result | Neyvia boundary and explicit write flag | Keep blocked until its local CLI responds |
| Prime Agent | adapter-ready, not installed | strict JSONL, retained sessions, ACP | bounded gates and Neyvia boundary | Install through the official checksummed installer in WSL/Git Bash |
| Pi | adapter-ready, not installed | JSONL, RPC, TypeScript SDK | no built-in permission system; Neyvia isolation is mandatory | Strong small-harness route; OpenCode Go capable |
| DeepSeek Harness | adapter-ready, not installed | headless text plus append-only session log | profile-selected sandbox/plugins | Developer preview; do not label final text as JSONL |
| gptme | adapter-ready, not installed | non-interactive JSONL, MCP, ACP | tool selection plus Neyvia boundary | Strong local-first optional route |
| Wallbreaker | external security adapter, not installed | text stream plus durable campaign log | orchestration-only, executor-only, explicit authorization | Never Direct chat; AGPL code stays external |
| Hermes | integrated orchestration runtime | CLI/runtime events | mission policy, receipts, controlled workspace | Keep as a runtime rail, not the only harness |
| OpenClaw | integrated orchestration/runtime bridge | CLI/runtime events | workspace and provider policy | Keep as a runtime rail, not the only harness |

Primary references: [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent),
[Pi](https://github.com/earendil-works/pi),
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness),
[gptme](https://github.com/gptme/gptme), and
[Wallbreaker](https://github.com/JailbrokenAI/wallbreaker).

## Researched next-wave candidates

| Candidate | Documented machine surface | Important control/evidence | Neyvia decision |
| --- | --- | --- | --- |
| Gemini CLI | non-interactive prompt; JSON and stream-JSON; resume | native/tool sandbox, MCP, screen-reader mode | High-priority adapter candidate after a live JSON-stream conformance test |
| Qwen Code | JSON, stream-JSON, bidirectional stream input, SDK | plan/default/auto-edit/yolo modes, optional Docker sandbox, MCP | High-priority adapter candidate; require sandbox for auto approval |
| Cline CLI | headless JSON, ACP, sessions, SDK | tool approvals, MCP, doctor, background hub | High-priority adapter candidate |
| Roo Code CLI | print mode and stream-JSON stdin protocol | modes with distinct tool groups and optional approval requirement | High-priority adapter candidate |
| GitHub Copilot CLI | programmatic prompt and JSONL | granular tool/path/URL permissions, plan/autopilot, sessions, skills, MCP | Optional subscription route; preserve model and permission receipts |
| Goose | CLI, desktop app, API, ACP providers, MCP | session identifiers and extension boundary | High-priority open-source candidate after CLI event audit |
| Amp | `--execute --stream-json` | proprietary provider/session policy | Optional external route; do not make a default dependency |
| Factory Droid | TypeScript/Python SDK, streaming sessions, daemon JSON-RPC | tool permission control; public SDK currently changing | Research until the SDK overhaul stabilizes |
| Aider | one-shot `--message`, dry-run and confirmation controls | strong Git workflow but no documented full tool-event JSONL | External one-shot adapter only, not a live-event harness |
| Crush | TUI/run commands, MCP, skills, sessions | trusted shell configuration executes at startup | Research only until a stable machine-event contract is documented |
| OpenHands CLI | headless JSON, MCP, resume | project explicitly says the CLI is no longer actively maintained | Do not add the legacy CLI; assess Agent Canvas / current SDK instead |
| SWE-agent | durable trajectories and inspectors | benchmark/experiment isolation | Evaluation framework, not an everyday chat harness |

Primary references:

- [Gemini CLI configuration and output formats](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md)
- [Qwen Code settings, stream protocol, and sandbox](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/settings.md)
- [Cline CLI reference](https://github.com/cline/cline/blob/main/docs/cli/cli-reference.mdx)
- [Roo Code CLI entrypoint](https://github.com/RooCodeInc/Roo-Code/blob/main/apps/cli/src/index.ts)
- [GitHub Copilot CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)
- [Goose](https://github.com/aaif-goose/goose)
- [Amp owner’s manual](https://ampcode.com/manual)
- [Factory Droid TypeScript SDK](https://github.com/Factory-AI/droid-sdk-typescript)
- [Aider scripting](https://aider.chat/docs/scripting.html)
- [Crush](https://github.com/charmbracelet/crush)
- [OpenHands CLI maintenance notice](https://github.com/OpenHands/OpenHands-CLI)
- [SWE-agent trajectory inspector](https://github.com/SWE-agent/SWE-agent/blob/main/docs/usage/inspector.md)

## Installation policy

Neyvia may show an uninstalled adapter with its official install command, but it must
not auto-run a remote installer. Installation stays an explicit operator action and
must preserve checksum/signature verification when the upstream provides it. Secrets
remain in the provider’s native login or an environment-variable reference; they are
never copied into the catalog or a run receipt.

## Ambitious, permissive execution without false claims

The shared instruction direction should encourage agents to continue through
recoverable friction, use available tools, test real behavior, and attempt the full
authorized task. It must not authorize unrelated external side effects, bypass a
workspace boundary, invent tool results, substitute providers silently, or call work
complete without evidence. “Unlazy” means persistent and resourceful, not reckless or
fictional.
