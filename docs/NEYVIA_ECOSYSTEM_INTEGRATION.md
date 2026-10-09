# Neyvia ecosystem integration

**Date:** 2026-07-23  
**Product name:** N-E-Y-V-I-A / Neyvia (never CapOS in UI)

## Workspace → ecosystem

Neyvia is an **ecosystem**, not just a workspace. External tools (Claude Code, Grok Build, PDF, research, translate, grammar, chart, web-capture, suite tools, library picks) when used **inside** Neyvia must perform better than alone — via shared session/constellation context, receipts/proof strip hooks, memory budgets, resilience (queued until harness receipt), app-share / session artifact access, and orchestration co-presence.

### Ranking (product rule)

1. **Neyvia’s own runtime** — strongest  
2. **Integrated lanes inside Neyvia** — stronger than standalone  
3. **Standalone tools** — baseline  

## Session tool pane layouts

Persisted in `neyviaShellPreferences.sessionToolPaneLayout` (`neyvia.shell.preferences.v1`):

| Mode | Behavior |
| --- | --- |
| `dock-right` (default) | Pane beside the live session; chat/orchestration keep running |
| `dock-left` | Same, left edge |
| `fullscreen` | Tool owns the viewport; restore returns to the live session |
| `floating-center` | Little window over the other agent — click to focus without interrupting |

Floating/docked panes are a **separate space**: focus, expand to fullscreen, interact without interrupting the other session/agent. Same host pattern for Claude Code managed-CLI and major tools.

Settings UI: **Settings → Ecosystem · session tool panes**.

## Silent ecosystem prompt rewrite

| Setting | Default | Meaning |
| --- | --- | --- |
| `silentEcosystemPromptRewrite` | **ON** | When attaching Claude Code / Grok Build (and when queueing lane messages), Neyvia silently injects ecosystem coaching (shared context, proof/approvals honesty, constellation linkage) |

This is **intentional ecosystem coaching**, not a thin clone of Claude Code and not CapOS branding. Neyvia identity in chrome stays **Neyvia / N-E-Y-V-I-A**.

Off = supervised lane only, no coaching prepend.

## Module map

| Piece | Path |
| --- | --- |
| Frontend ecosystem layer | `web/src/neyvia/neyviaEcosystem.js` |
| Session pane host | `web/src/neyvia/NeyviaSessionToolPanes.jsx` |
| Preferences | `web/src/neyvia/neyviaShellPreferences.js` |
| Settings | `web/src/neyvia/NeyviaShellSettings.jsx` |
| Overlay + session host | `web/src/neyvia/NeyviaShellSurfaces.jsx` → `NeyviaShellOverlayHost` |
| Backend pack / rewrite | `src/grant_agent/neyvia_ecosystem.py` |
| Web command | `build_neyvia_ecosystem_context_pack_command` |

## Honesty

- Never invent successful executions.  
- `agentReady` stays backend-truthful (see `docs/NEYVIA_CAPABILITY_CLAIM_AUDIT.md`).  
- App-share / library hooks surface **connected** state only when real.  
- Prefer efficiency: lazy-mount panes, tear down when closed, respect reduce-motion.

## Related

- `docs/NEYVIA_CLAUDE_CODE_ORCHESTRATION.md` — managed-CLI lane + silent rewrite  
- `docs/NEYVIA_GROK_BUILD_CLAUDE_CODE_RESEARCH.md` — BYO lanes inside a proof-grade OS  
- `docs/NEYVIA_CAPABILITY_CLAIM_AUDIT.md` — claim hygiene  
