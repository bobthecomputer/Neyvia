# Neyvia research: Grok Build + Claude Code

**Date:** 2026-07-23  
**Scope:** Source-verified product facts for Anthropic Claude Code and xAI Grok Build, plus Neyvia/Fluxio integration implications.  
**Method:** Official docs/release pages fetched and quoted; third-party blogs treated as non-authoritative.  
**Local context:** Repo managed-CLI adapters, harness gateway notes, NAS/Hermes routing docs — no credentials published.

**Speech/intent notes (operator):** “Grok Build” + “Claude Code”; “cloud code on the NAS (MS)” interpreted as **Claude Code** (and/or Claude cloud sessions) praised on the managed Synology/runtime host; “GruntBald / Grog Bird fans” interpreted as **community interest in Grok Build / Claude Code**.

---

## 1. What each product is (verified)

### 1.1 Claude Code (Anthropic)

**Primary definition** (official overview, fetched 2026-07-23):

> Claude Code is an agentic coding tool that reads your codebase, edits files, runs commands, and integrates with your development tools. Available in your terminal, IDE, desktop app, and browser.

**Verified surfaces**

| Surface | Official claim |
| --- | --- |
| Terminal CLI (`claude`) | Full-featured CLI; native install scripts for macOS/Linux/WSL and Windows; also Homebrew / WinGet |
| VS Code / Cursor extension | Inline diffs, @-mentions, plan review, conversation history |
| Desktop app | Diff review, multiple sessions, scheduled tasks, cloud sessions (paid subscription required) |
| Web | `claude.ai/code` — long-running / parallel tasks without local setup |
| JetBrains | Plugin + separately installed CLI |

**Auth / access (official):** Most surfaces require a Claude subscription or Anthropic Console account. Terminal CLI and VS Code also support third-party providers.

**Core workflow primitives (official overview + related docs)**

- Project instructions via `CLAUDE.md`, skills, hooks, MCP
- Git commits / PRs; CI via GitHub Actions / GitLab CI/CD
- Headless / Unix-composable: `claude -p "..."` (pipe, script, CI)
- Session mobility: Remote Control, `claude --teleport`, `/desktop`, Slack `@Claude`
- **Agent teams** (experimental, off by default): enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`; lead + independent teammates with shared tasks; known limitations on resumption/coordination/shutdown; documented as of v2.1.178+
- **Agent SDK** (Python / TypeScript): same agent loop/tools as Claude Code as a library; for other languages use CLI `-p` + `--output-format json`. Distinct from Anthropic Client SDK (you implement tools) and Managed Agents (hosted REST)

**Model claims:** Official overview does **not** pin a single public “always Opus 4.6” string on the landing page. Do not treat third-party Medium claims about star counts or default model as fact without Anthropic confirmation.

**Sources:** [Overview](https://code.claude.com/docs/en/overview), [Agent teams](https://code.claude.com/docs/en/agent-teams), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Costs](https://code.claude.com/docs/en/costs), docs index [llms.txt](https://code.claude.com/docs/llms.txt)

---

### 1.2 Grok Build (xAI / SpaceXAI branding on x.ai)

**Primary definition** (official docs overview, fetched 2026-07-23):

> Grok Build is a powerful and extensible coding agent. Use it via an interactive TUI, headlessly in scripts or bots, or through the Agent Client Protocol (ACP) in other apps.

**Launch / open-source timeline (official news)**

| Date | Event | Source |
| --- | --- | --- |
| 2026-05-25 | Early beta launch for SuperGrok and X Premium Plus subscribers; terminal coding agent + CLI | [Introducing Grok Build](https://x.ai/news/grok-build-cli) |
| 2026-07-15 | Open-sourced harness + TUI; local-first via `config.toml` + own inference | [Grok Build is Now Open Source](https://x.ai/news/grok-build-open-source) |

**Verified capabilities (official)**

- Interactive fullscreen TUI; install via `curl … install.sh` / PowerShell `irm … install.ps1`
- Auth: browser login on first launch, or `XAI_API_KEY` for non-browser
- Plan mode with approve / comment / rewrite before execution; diffs after approval
- Parallel **subagents** + deep **worktree** integration
- Headless: `grok -p "…"`, optional `--output-format streaming-json`
- **ACP**: `grok agent stdio`
- Custom models in `~/.grok/config.toml` (`[model.*]`, `[models] default`)
- Default powering model named on docs/API pages as **`grok-4.5`** (exact string from xAI docs)
- Extension system: skills, plugins, hooks, MCP, marketplaces, subagents
- **Claude Code compatibility (official, zero-config):** reads Claude marketplaces, plugins, skills, MCPs, agents, hooks, and `CLAUDE.md` / `.claude/rules/` alongside `.grok/`
- Also reads `AGENTS.md` family and Cursor-compatible paths (toggleable via `[compat.claude]` / `[compat.cursor]` / env flags)
- Session import from Claude Code: `grok import`
- Discovery/debug: `grok inspect [--json]`
- Open source: [github.com/xAI-org/grok-build](https://github.com/xAI-org/grok-build) (Rust harness; binary shipped as `grok`)

**Sources:** [docs overview](https://docs.x.ai/build/overview), [skills/plugins/compat](https://docs.x.ai/build/features/skills-plugins-marketplaces), [AGENTS.md / project rules](https://docs.x.ai/build/features/project-rules), [CLI reference](https://docs.x.ai/build/cli/reference), [product page](https://x.ai/cli), news posts above

---

### 1.3 Side-by-side (facts only)

| Dimension | Claude Code | Grok Build |
| --- | --- | --- |
| Vendor | Anthropic | xAI (SpaceXAI branding on x.ai) |
| Primary UX | CLI + IDE + Desktop + Web | Terminal TUI (+ ACP + headless) |
| Headless | `claude -p` | `grok -p` (+ streaming-json) |
| Embed API | Agent SDK (Py/TS) + CLI JSON | ACP (`grok agent stdio`) + headless |
| Parallelism | Subagents; experimental agent teams | Parallel subagents + worktrees |
| Project memory | `CLAUDE.md`, skills, hooks, MCP | `.grok/` + **imports Claude + AGENTS.md + Cursor paths** |
| Open source harness | Not claimed as OSS harness on overview | OSS as of 2026-07-15 |
| Default model string (docs) | Subscription/API models; CLI aliases vary | `grok-4.5` on Build/API docs |

---

## 2. What Neyvia can learn

### 2.1 Multi-agent efficiency

| Pattern | Who | Lesson for Neyvia |
| --- | --- | --- |
| Lead + independent teammates with shared task list | Claude agent teams | Prefer **mission-owned** shared task board + lane IDs over copying experimental env flags; gate parallel spawn by independence of work (official Claude warning: sequential/same-file → single session cheaper) |
| Parallel digs in worktrees | Grok Build | Make **worktree-per-lane** a first-class orchestration primitive with cleanup receipts (`worktree gc` analogue) |
| Subagents vs teams | Claude docs | Keep two Neyvia modes: **report-back workers** (cheap) vs **peer-messaging lanes** (expensive, need proof of coordination value) |
| Plan-before-edit | Both | Keep plan approval as a **supervisor object** (Neyvia receipt), not only inside the child CLI |

### 2.2 UX

| Pattern | Lesson |
| --- | --- |
| Plan review + clean diffs before/after execute | Grok launch messaging; Claude plan mode / VS Code plan review | Fluxio Builder should surface **plan → approve → diff proof** as one composition, not a dashboard of widgets |
| `inspect` / discovery of loaded skills, rules, MCP | Grok `grok inspect` | Ship a **Harness Inspect** card: what CLAUDE.md / AGENTS.md / MCP / skills each runtime actually loaded |
| Session mobility (teleport, desktop, web) | Claude | NAS + desktop should **resume the same mission id** across surfaces with one receipt trail |
| Extensions modal (skills/hooks/MCP) | Grok TUI | One operator surface to attach skills; do not re-implement each harness’s marketplace UI |

### 2.3 Tool calling

| Pattern | Lesson |
| --- | --- |
| Progressive / built-in tools + MCP | Both + Hermes/OpenCode already in Neyvia audit | Keep Neyvia `search → describe → validate → authorize → call → receipt` as the **OS layer**; harness tools stay native |
| Claude Agent SDK vs Client SDK | Anthropic | Prefer supervising CLIs/ACP over re-implementing tool loops; optional SDK only when Neyvia needs in-process Claude loop |
| Grok custom model `config.toml` | xAI | Align with Fluxio harness profiles / CLIProxy — operator-owned base URL + env key names, never browser-visible tokens |
| Claude flag aliases on Grok CLI | Official CLI ref | When bridging, prefer **documented flag aliases** over inventing a third dialect |

### 2.4 Proof

| Pattern | Lesson |
| --- | --- |
| Headless JSON / streaming-json | Both | Normalize into Fluxio runtime events + mission receipts (already direction of `managed_cli` / `external_cli_bridge`) |
| Diff-as-proof after plan approve | Grok | Persist plan hash + diff digests as proof artifacts |
| Agent team limitations | Claude | Do not claim “team resume” until Neyvia owns resume; use mission state as source of truth |
| Open harness source | Grok OSS | Use open source as **reference for dispatch/context assembly**, not as a fork-to-wrap strategy |

---

## 3. Local / NAS context (repo — no secrets)

Already present in this workspace (implementation + docs):

| Area | Finding |
| --- | --- |
| Managed CLIs | `claude-code` and `grok-build` are first-class in `MANAGED_CLI_SPECS` / `neyviaProductMode.js` (defaults: Claude alias `sonnet`, Grok `grok-4.5`) |
| Adapters | `ClaudeCodeRuntimeAdapter`, `GrokBuildRuntimeAdapter`; Grok `supports_acp=True`, Claude `supports_acp=False` in current specs |
| Bridge | `external_cli_bridge.py` supports `kimi-code`, `claude-code`, `grok-build` headless JSON → Fluxio events |
| Gateway | `.codex-nas-stage/docs/harness-gateway-architecture.md`: CLIProxyAPI loopback pool; Claude Code Router; **do not flatten** native `CLAUDE.md` / Grok Claude-compat paths |
| Operator helper | `scripts/claudex.ps1` — Claude via CLIProxyAPI (`ANTHROPIC_BASE_URL`), separate from plain `claude` |
| NAS posture | Synology docs: Hermes/OpenClaw/Codex install on the **NAS host**, not the operator PC; Hermes historically strong for long-horizon missions |
| Differentiation already stated | `NEYVIA_NATIVE_RUNTIME.md`: Neyvia owns harness, policy, receipts, proof; external CLIs remain pluggable executors |
| Competitive gap | `SYSTEM_GAP_ANALYSIS.md` references T3-style BYO Claude/Codex/OpenCode wrappers — Neyvia must win on **mission proof + supervision**, not on “another CLI picker” |

**Interpretation of “cloud code on NAS is very good”:** Treat as operator preference for **Claude Code–class coding quality** (and possibly Claude cloud/web sessions) when available on the managed runtime host — not as a separate product named “Cloud Code.” MiniMax / OpenCode / Hermes remain routing options in-repo; do not collapse them into Claude/Grok.

---

## 4. How Neyvia should integrate (differentiated OS, not thin wrapper)

### Non-goals (wrapper smell)

- Rebranding `claude` / `grok` behind a skin
- Flattening `CLAUDE.md` / `.grok` / skills into one generic mega-prompt
- Claiming agent-team or ACP features the child runtime does not expose
- Shipping marketplace UIs that duplicate Grok/Claude instead of supervising them

### Differentiation pillars

1. **Mission OS:** planner / executor / verifier lanes, approvals, resume, recovery — owned by Neyvia regardless of which CLI executes a turn  
2. **Honest harness:** preserve native project context; show `inspect`-style discovery in Fluxio  
3. **Proof grade:** every lane writes receipts, tool receipts, plan digests, diff digests; failed tools stay failed  
4. **Multi-runtime composition:** Claude for deep coding / agent teams; Grok for ACP + Claude-compat + worktrees; Hermes for long-horizon; OpenCode for LSP-oriented coding — **routed by task-fit**, not fashion  
5. **Gateway hygiene:** CLIProxyAPI / profiles on loopback; tokens never in browser payloads (already documented)  
6. **Modify OSS only at the edges:** prefer adapters, event normalizers, and optional patches to open Grok harness **for observability hooks** — not a permanent fork that lags upstream

### Concrete integration moves

| Move | Why it rates higher than T3-style BYO |
| --- | --- |
| Supervise Claude via headless JSON + optional Agent SDK later | Same engine, Neyvia-owned policy/proof |
| Prefer Grok ACP + `-p` streaming-json for embed | Official orchestration surface |
| Cross-harness mission: e.g. Grok explore worktrees → Claude implement → Neyvia verify | No single vendor does this as an OS |
| Shared skill packs mapped to native skill dirs without rewriting content | Portable operator investment |
| `grok import` / Claude session continuity → Neyvia mission attach | Session becomes durable product state |
| NAS doctor + runtime auto-update receipts | Private deployment trust T3 web GUI does not own |

---

## 5. Product recommendations (P0–P2)

### P0 — ship or harden now

1. **Parity proof for managed Claude Code + Grok Build on NAS**  
   One scripted mission each: headless prompt → normalized events → receipt → artifact. Block “ready” until both pass.  
2. **Harness Inspect UI**  
   Surface loaded rules/skills/MCP the way `grok inspect` does; for Claude, show discovered `CLAUDE.md` / `.claude/*` without inventing features.  
3. **Plan → approve → diff proof path** for Builder/orchestration  
   Align UX with Grok/Claude plan modes; store plan + diff digests in mission proof.  
4. **Keep gateway contract strict**  
   CLIProxyAPI / Claude profiles: loopback only, no token in browser, no silent credential copy (already in harness-gateway doc — treat as release gate).

### P1 — clear differentiation

5. **Worktree-per-lane orchestration** (inspired by Grok) with Neyvia cleanup receipts  
6. **ACP lane for Grok Build** (`grok agent stdio`) beside headless JSON; document when each transport is used  
7. **Task-fit routing recipes**  
   Example: explore/parallel → Grok; implementation depth → Claude; long-horizon → Hermes; LSP/edit precision → OpenCode — with route mutation receipts  
8. **Claude agent teams as opt-in experimental lane**  
   Only when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is operator-enabled; Neyvia mission board remains source of truth; label experimental limitations in UI

### P2 — deepen the OS

9. Optional **Claude Agent SDK** in-process worker for embedded tools under Neyvia policy (not a replacement for CLI supervision)  
10. Selective study of **open Grok Build** agent-loop / tool-dispatch for observability inspiration; contribute upstream rather than maintain a divergent fork  
11. Session import bridge: Claude ↔ Grok (`grok import`) ↔ Neyvia mission attach  
12. Community-facing narrative: “BYO Claude Code & Grok Build **inside a proof-grade mission OS**” — directly counters thin-wrapper perception

### Alignment note (2026-07-23 ecosystem upgrade)

Product now frames Neyvia as an **ecosystem**: integrated Claude Code / Grok Build lanes get silent ecosystem coaching (default ON) plus co-present session tool panes (dock/float/fullscreen). Own runtime remains strongest; integrated lanes must beat standalone. See `docs/NEYVIA_ECOSYSTEM_INTEGRATION.md` and `docs/NEYVIA_CLAUDE_CODE_ORCHESTRATION.md`. CapOS remains inspiration-only naming.

---

## 6. Claim hygiene (search-verification)

| Claim | Status |
| --- | --- |
| Claude Code = Anthropic agentic coding tool, multi-surface | **Verified** — code.claude.com overview |
| Agent teams experimental + env flag | **Verified** — agent-teams docs |
| Agent SDK = Claude Code loop as library | **Verified** — agent-sdk overview |
| Grok Build early beta 2026-05-25; OSS 2026-07-15 | **Verified** — x.ai news |
| Grok Claude-compat zero-config | **Verified** — docs.x.ai skills page |
| Default model string `grok-4.5` for Build/API examples | **Verified** — docs.x.ai overview |
| GitHub star counts / “Opus 4.6 always” from Medium | **Unverified** — do not use as product truth |
| Product named “Cloud Code” on NAS | **Not found** as separate vendor product; interpret as Claude Code / cloud Claude sessions |

---

## 7. Sources (URLs)

### Claude Code / Anthropic

- https://code.claude.com/docs/en/overview  
- https://code.claude.com/docs/llms.txt  
- https://code.claude.com/docs/en/agent-teams  
- https://code.claude.com/docs/en/agent-sdk/overview  
- https://code.claude.com/docs/en/agent-sdk/quickstart  
- https://code.claude.com/docs/en/costs  

### Grok Build / xAI

- https://x.ai/cli  
- https://x.ai/news/grok-build-cli  
- https://x.ai/news/grok-build-open-source  
- https://docs.x.ai/build/overview  
- https://docs.x.ai/build/features/skills-plugins-marketplaces  
- https://docs.x.ai/build/features/project-rules  
- https://docs.x.ai/build/cli/reference  
- https://docs.x.ai/build/settings/reference  
- https://github.com/xAI-org/grok-build  

### Local Neyvia references (this repo)

- `docs/NEYVIA_NATIVE_RUNTIME.md`  
- `docs/SYSTEM_GAP_ANALYSIS.md`  
- `docs/SYNOLOGY_NAS_SETUP.md`  
- `.codex-nas-stage/docs/harness-gateway-architecture.md`  
- `src/grant_agent/runtimes/managed_cli.py`  
- `web/src/neyvia/neyviaProductMode.js`  
- `scripts/claudex.ps1`  

---

*End of research note. Not committed. No credentials included.*
