# Claude Code in Neyvia Orchestration

**Date:** 2026-07-23 (updated ecosystem pane + silent rewrite)  
**Product name:** N-E-Y-V-I-A / Neyvia (never CapOS)

## System-prompt / coaching decision

**Shipped default:** Claude Code (and optionally Grok Build) attach as an **orchestrated interactive managed-CLI session lane** inside Orchestration — a specialist/session pane other constellation participants can interact with.

**Silent ecosystem prompt rewrite (Settings, default ON):** When enabled, Neyvia **silently** injects ecosystem coaching into the integrated lane (shared session/constellation context, proof/approval honesty, capability-snapshot awareness, memory budgets). This is intentional so **inside Neyvia > standalone**. It is **not** a thin Claude Code clone of Neyvia’s own runtime, and chrome stays N-E-Y-V-I-A.

| Option | Pros | Cons | Decision |
| --- | --- | --- | --- |
| Overwrite Neyvia OS identity with Claude Code’s prompt | Feels “like Claude Code” in one box | Contaminates Neyvia identity, policy, proof ownership | **Rejected** |
| Orchestrated managed-CLI lane + session tool pane host | Keeps native Claude Code context; Neyvia owns mission/approval/proof; co-present dock/float/fullscreen pane | Requires harness bridge for live turns | **Shipped default** |
| Silent ecosystem rewrite (toggle, default ON) | Lane gets ecosystem advantages without operator friction | Must stay honest (no fake success) | **Shipped** — Settings → Ecosystem |
| Optional “make Neyvia native turns sound like Claude Code” | Explicit style choice | Easy to over-claim | Still not the product identity path |

## Session tool pane host

Managed CLI uses the same session-pane host as PDF / research / translate / grammar / chart / web-capture / library tools:

- Layout from Settings (`sessionToolPaneLayout`): **dock right**, **dock left**, **fullscreen**, **floating center**
- Click to focus; expand to fullscreen; interact without interrupting the other agent
- Lazy-mount / tear down when closed; respect reduce-motion

See `docs/NEYVIA_ECOSYSTEM_INTEGRATION.md`.

## How to use (operator)

1. Open **Settings → Ecosystem · session tool panes** — pick layout; leave **Silent ecosystem prompt rewrite** ON (or turn off).
2. Open **Orchestration** (Chat ↔ Orchestration pivot).
3. In **Managed CLI lane**, choose **Claude Code** (or Grok Build).
4. Click **Attach Claude Code** — adds a constellation role (`runtime: claude-code`), applies silent rewrite when enabled, and opens the **managed-cli** session pane.
5. Optionally **Harness inspect** — discovery of router/CLIProxy/snapshot truth (honest empty if command missing).
6. Type in the session / lane composer → **Send turn** — the message runs through the same durable runtime invocation used by primary and inline surfaces. The pane renders the real assistant and tool events returned by the adapter; unavailable or failed runtimes remain visibly blocked. With rewrite ON, ecosystem coaching is applied by the backend once.
7. Use **Decompose / Focus Grid** so other agents and the Claude Code lane share the same constellation.

## Wiring notes

- Ecosystem pack: `web/src/neyvia/neyviaEcosystem.js` + `src/grant_agent/neyvia_ecosystem.py`
- Web command: `build_neyvia_ecosystem_context_pack_command`
- UI: `web/src/neyvia/NeyviaProductModePanels.jsx` → `neyvia-managed-cli-session`
- Session panes: `NeyviaSessionToolPanes.jsx` / `NeyviaShellOverlayHost`
- Shell actions: `orchestration:managed-cli:attach`, `orchestration:managed-cli:message` in `NeyviaShell.jsx` (no silent agent fallthrough)
- Claim-audit P0 for tools remains separate: Wave-1 suite `agentReady` → plan → approve → execute

## Remaining gaps

- Live headless/ACP turn streaming into the session pane (bridge receipt → transcript)
- Full Harness Inspect parity with `grok inspect` / CLAUDE.md tree listing
- Backend apply of rewrite on actual CLI child process (UI + pack command ready; bridge merge still thin)
