# Codex App Feature Catch-Up List

Checked on 2026-05-04 against official OpenAI pages:

- OpenAI, "Introducing the Codex app", published 2026-02-02 and updated 2026-03-04:
  https://openai.com/index/introducing-the-codex-app/
- OpenAI, "Codex for (almost) everything", published 2026-04-16:
  https://openai.com/index/codex-for-almost-everything/
- OpenAI Academy, "Automations", published 2026-04-23:
  https://openai.com/academy/codex-automations/
- OpenAI Help Center, "Using Codex with your ChatGPT plan", checked 2026-05-04:
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan

## Product Surface To Match

- Desktop command center for multiple agents running in parallel.
- Project/thread organization with session continuity from CLI and IDE configuration.
- Isolated worktrees for parallel agents, with reviewable diffs.
- Diff comments and editor handoff for manual edits.
- Long-horizon/background tasks with visible progress and decisions.
- Reusable skills, skill creation, and skill management.
- Automations that schedule background work and land results in a review queue.
- Personality selection through `/personality`.
- Native sandboxing and project/team rules for elevated commands.
- Windows desktop availability in addition to macOS.

## April 2026 Catch-Up Items

- Background computer use: agent sees, clicks, and types with its own cursor.
- In-app browser with direct page comments for frontend/game iteration.
- Image generation and image iteration in the same coding workflow.
- More than 90 plugins combining skills, app integrations, and MCP servers.
- GitHub review-comment addressing.
- Multiple terminal tabs.
- Remote devbox connections over SSH.
- Sidebar file previews for PDFs, spreadsheets, slides, and docs.
- Summary pane for agent plans, sources, and artifacts.
- Automations that can reuse existing conversation threads and wake later.
- Recurring automations for morning briefs, weekly summaries, folder checks, cleanup jobs, status updates, and similar reviewable work.
- Preview memory for preferences, corrections, and gathered context.
- Context-aware suggestions for next useful work.
- Browser-based work, image generation, memory, and ongoing work across tools and apps are explicitly part of the "beyond coding" direction.

## Implications For Neyvia

- NAS/web mode must not be treated as read-only for model auth. It should support API-key/env auth, runtime-provided OAuth state, and manual OpenClaw/Hermes auth commands where desktop keyring OAuth is unavailable.
- Route selection must persist before launch, otherwise the model dropdown looks usable but missions still run with stale/default routes.
- Hermes/OpenClaw lanes should become the reliable bridge for phone/NAS auth and approvals, not a separate optional experiment.
- The next UI parity targets are browser comments, terminal tabs, SSH/devbox routing, file previews, and a concise plan/source/artifact summary pane.
- Local/NAS authentication needs one authoritative persisted account store per deployed release, with explicit password writes and reload/restart behavior.
- Deletes in local admin lists need tombstones or backend-backed deletes so stale snapshots do not resurrect removed items.
