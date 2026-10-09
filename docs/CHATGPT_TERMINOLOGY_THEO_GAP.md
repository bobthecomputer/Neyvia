# ChatGPT Terminology + Theo Feature Gap (Fluxio)

Date: `2026-04-17`

Purpose: use official ChatGPT terminology, map Theo's UX ideas to real product primitives, and define a full `P0` -> `P3` implementation plan for Fluxio.

## Official ChatGPT Terms (use these names in specs)

Primary OpenAI Help Center references:

- `Projects`  
  Source: <https://help.openai.com/en/articles/10169521-using-projects-in-chatgpt>
- `Tasks` (scheduled runs, recurring runs, API-triggerable automation)  
  Source: <https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt>
- `Canvas`  
  Source: <https://help.openai.com/en/articles/9930697>
- `Memory` (`Saved memories` + `Chat history`)  
  Source: <https://help.openai.com/en/articles/8983136-what-is-memory>
- `Temporary Chat`  
  Source: <https://help.openai.com/en/articles/8914046-temporary-chat-faq>
- `Apps` / `Connectors` (external data and tools in chat)  
  Source: <https://help.openai.com/en/articles/11487775-connectors-in-chatgpt>
- `GPTs` / `GPT Builder`  
  Source: <https://help.openai.com/en/articles/8554397-creating-a-gpt>

## Theo Ideas -> ChatGPT Concept -> Fluxio Status

- Multi-folder context before a session  
  ChatGPT concept: `Projects`  
  Fluxio status: `Partial` (multi-workspace exists, but mission-level multi-folder context is still limited)

- Split / tiled conversation views  
  ChatGPT concept: UI capability (not a standalone primitive)  
  Fluxio status: `Missing`

- Automated routines with schedule/API/webhook triggers  
  ChatGPT concept: `Tasks`  
  Fluxio status: `Partial` (night mode scheduler exists; general mission/workspace task system does not)

- Integrated preview browser with network/debug logs  
  ChatGPT concept: `Canvas` + preview tooling behavior  
  Fluxio status: `Partial` (preview modes exist; full integrated debug panel is missing)

- Git worktree-aware sessions  
  ChatGPT concept: not a native ChatGPT primitive; implementation detail for coding agents  
  Fluxio status: `Present/Partial` (`isolated_worktree` exists; UX and guardrails still need hardening)

- Fast model/version switching  
  ChatGPT concept: model picker  
  Fluxio status: `Present/Partial` (provider/model/effort controls exist; quick presets still missing)

- Reliable copy/paste and screenshot attachment flow  
  ChatGPT concept: composer + attachments quality bar  
  Fluxio status: `Partial`

- Robust side-by-side diff with wrap toggle  
  ChatGPT concept: review UX capability  
  Fluxio status: `Partial` (proof summaries exist, strong side-by-side diff UI is still missing)

- Keyboard shortcuts scoped to active pane/tab only  
  ChatGPT concept: expected desktop UX behavior  
  Fluxio status: `At risk` (global overlay shortcuts are handled; local scope policy still needs tightening)

- Smooth performance with very long histories  
  ChatGPT concept: performance contract  
  Fluxio status: `Missing` (no explicit transcript virtualization in long-run paths)

- Fast project picker with search + visual project identity  
  ChatGPT concept: `Projects` ergonomics  
  Fluxio status: `Partial`

- Instant tab switching via pre-render/cache  
  ChatGPT concept: UX performance capability  
  Fluxio status: `Missing`

- Drag-and-drop reordering for chats/pins/sidebar  
  ChatGPT concept: UX capability  
  Fluxio status: `Missing`

## Implementation Plan (P0 -> P3)

## P0 - Reliability and Interaction Basics (must ship first)

- Composer attachment reliability: screenshot/image paste always attaches to the active draft.
- Global clipboard affordances: copy buttons for code, file paths, workspace IDs, mission IDs.
- Keyboard scope policy: local shortcuts affect only the selected pane/view.
- Transcript performance: virtualized rendering for long message and trace streams.

Acceptance criteria:

- `Ctrl+V` image in active composer creates a visible pending attachment in that composer only.
- All surfaced paths and IDs in mission/workspace detail areas have one-click copy.
- Opening/closing side panels does not reroute local shortcuts to hidden panes.
- No perceptible freezes with `5,000+` timeline items in profiling scenarios.

## P1 - Core UX Differentiators

- Split/tiled mission chat view (2-3 parallel panes).
- Strong side-by-side diff viewer with soft-wrap toggle and stable rendering.
- Project picker with instant search and visual identity (icon/folder marker).
- Quick model presets for role-specific workflows (`coding`, `review`, `planning`).

Acceptance criteria:

- Two missions can remain open side-by-side without context reset.
- Diff view remains usable on narrow desktop widths without broken layout.
- Project search remains sub-100ms on a simulated large project list.
- Preset switching updates route controls in one click with visible effective route confirmation.

## P2 - Automation and Debug Surface

- Generic task system aligned to `Tasks`: scheduled, recurring, API-triggered, webhook-triggered.
- In-app preview/debug panel: runtime logs, network requests, JS/Tauri error stream.
- Drag-and-drop ordering for sidebar entities (chats, pins, workspaces).

Acceptance criteria:

- Users can create, pause, resume, and delete tasks in UI.
- Task executions produce timeline entries and completion evidence.
- Reordered sidebar state persists across restart.
- Debug panel can capture at least one successful and one failed request with timestamps.

## P3 - Scale, Governance, and Polishing

- Memory policy layer for Fluxio-native context retention (`mission memory`, `project memory`, explicit clear/reset).
- Pre-rendered tab/session cache for near-instant pane switching under load.
- Accessibility and desktop hardening pass (keyboard nav, focus rings, screen-reader labels, high-contrast checks).
- Long-run resilience pass: restore state after restart with deterministic replay of trace + approvals + task status.

Acceptance criteria:

- Operators can clear mission-scoped memory without clearing project-level context.
- Warm tab switch latency is consistently low under stress test scenarios.
- Keyboard-only operation passes for all primary mission actions.
- Restart while active missions/tasks exist resumes with no orphaned lane state.

## Execution Order

1. Implement `P0` completely and freeze regressions.
2. Deliver `P1` UX primitives in thin vertical slices.
3. Add `P2` automation/debug features on top of stable interaction contracts.
4. Finish with `P3` scale/governance hardening.

Do not start `P2` or `P3` before `P0` acceptance gates pass.

## Primary Code Targets in This Repo

- Shell UI: `web/src/neyvia/NeyviaShell.jsx`
- Shell styles: `web/src/neyvia/styles.css`
- Desktop bridge and runtime plumbing: `src-tauri/src/lib.rs`
- Existing release polish context: `docs/FLUXIO_1_0_POLISH_PLAN.md`

## Team Vocabulary Policy

Use these terms exactly in product tickets, PRs, and docs:

- `Projects`
- `Tasks`
- `Canvas`
- `Memory`
- `Temporary Chat`
- `Apps` (legacy wording: `Connectors`)

Fluxio-native terms:

- `Mission`
- `Workspace`
- `Runtime lane`
- `Proof`
- `Execution target` (`direct` / `isolated_worktree`)
