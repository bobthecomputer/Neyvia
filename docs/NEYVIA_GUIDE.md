# Neyvia Guide

Neyvia is a workspace for AI agents. You can chat with one assistant about a
project folder, or give a bigger goal to a team of agents and follow their work.
This guide covers the everyday path. Operators who install, verify, and release
Neyvia should also read [the operator guide](NEYVIA_OPERATOR_GUIDE.md).

The first visit opens a three minute setup: a one minute tour of what makes
Neyvia different, then your downloads (Core is on; the Claude Code mod, Neyvia
skills for Codex and optional packs are one switch each), then your agent
connections. Every step can be skipped. Setup stays in the sidebar menu, and the
tour is under **Help**, or press `Ctrl+Space` and type "different".

## Open Neyvia

From a source checkout, run:

```
npm run neyvia
```

The launcher waits until the backend is healthy, then opens the workspace. While
it starts you see the Neyvia star. It stays up until your conversations have
loaded, so the workspace never appears half-empty. If the connection drops during
startup, the same screen offers **Reload workspace**.

## Start a chat

1. Click **New Chat** in the sidebar.
2. Type what you want in plain words, then press the send arrow.
3. Pick a starting point card instead if you want a template: explain a concept,
   write or refactor code, answer a technical question, summarize a document,
   analyze data or logs, or brainstorm.

### The message box

The row under the message box holds every choice for this chat:

| Control | What it does |
| --- | --- |
| **+** | Attach files or a folder, pick up recent context, load a workflow, use a skill or app, open Preview or Terminal, and change chat settings. |
| **Runtime** | Which agent does the work: Neyvia Native, Codex, Claude Code, Grok Build, Kimi Code, OpenCode, Hermes, or OpenClaw. |
| **Workspace** | The project folder the agent works in. **Add folder** browses local or NAS folders. |
| **Access** | **Read-only** only looks. **Workspace tools** can edit the project. **Full access** can also run commands without asking first. |
| **Model** | The model for this chat. **Browse all providers and models** lists everything you have connected. |
| **Reasoning** | Slide right for more thinking on harder problems. |
| **Microphone** | Dictate instead of typing. |

Chat settings live in the **+** menu under **This chat**:

- **Mode**: Standard, Plan (writes a plan before editing files), Fast (low
  effort, short budget), or 1M context (deep run with an extended budget).
  Each click moves to the next mode.
- **Storage**: Automatic, NAS shared, or local only.
- **System prompt**: edit the instructions for this chat.

Use the arrow keys to move through the **+** menu and `Escape` to close it.

## Follow the work

Each reply shows what the agent did, in the order it happened, above the answer:

- **Thoughts** have a gold dot. A short title says what the agent is thinking
  about; long thoughts can be expanded.
- **Tool calls** have their tool's icon: **Ran** a command, **Read** a file,
  **Searched**, **Opened** a page, **Edited** or **Created** a file.
- **File edits** open on their diff, with added and removed line counts.
- Click any step to see its details: the full command and its output, the file
  contents, or the raw input and result.

While the agent works, the header reads **Working** with a timer, the current
step pulses, and the conversation follows new activity. Scroll up to read
something earlier and the view stays put; a **New activity** button brings you
back to the latest step. When the reply is finished, the header reads
**Worked for …** with the number of thoughts and tool calls. Click it to fold
the activity away. Neyvia remembers that choice.

If a reply is stopped or interrupted, the message says so and offers
**Continue from here** or **Restore original message**.

## Find past work

The sidebar lists your conversations:

- **Priority** puts conversations that need you at the top.
- **Recent** sorts by last activity.
- **Projects** groups conversations by workspace.
- **Search titles and content** finds past work by what was said.

## Bigger goals: orchestration

**New Orchestration** splits a goal across several agents. You describe the goal,
review the plan, and approve it before the team starts. The orchestration view
shows which agent is doing what, what is blocked, and what is ready for your
review. Approvals appear as a **Decision required** banner with **Review**,
**Reject**, and **Approve**.

**Workflows** opens **Choose a workflow**: templates such as *Research a topic*,
*Fix a failing test*, *Review my changes*, *Watch a long run*, *Document what
changed*, and *Pull data out of documents*, plus your **Saved** workflows.
Loading one fills in the plan, message, and agent team so you can edit them
before you start.
**Session map** shows how conversations and branches relate.

## Other spaces

The footer of the sidebar opens the rest of Neyvia:

- **Notebook**: keep source documents, research, and lessons together.
- **Lab**: test code, models, devices, 3D, and media in one supervised workspace.
- **Library**: skills, tools, and domain capability packs available to your workspace.
- **Images**: image generation.
- **Marketplace**: browse and install apps.
- **Phone status**: connect and check the phone companion.
- **Devices** and **Updates** (top right): connected devices and app updates.

## Settings

**Settings** in the sidebar has these sections:

- **Models & Accounts**: connect providers and sign in to runtimes.
- **Workspace**: the project folder Neyvia may read and change.
- **Updates**: check for and apply updates.
- **Appearance**: theme, light or dark, and text size.
- **Personalization**: your standing guidance, such as how you like to work and the visual direction you prefer. Your current request always takes priority.
- **Accessibility**: reduced motion, focus indicators, and more.
- **Rules & Routing**: the agent harness settings and the prompt library, with system prompts for chat and each role (reader, planner, executor, verifier).
- **Runtimes & Rooms**: installed agent runtimes, what each needs to connect, and the exact model route it uses.
- **Databases**: where conversation history, mission receipts, context memory, and artifacts are stored.
- **Team Manager**: the default orchestration team (planner, executor, verifier) and the model each one uses.

## Keyboard and accessibility

- `Tab` and `Shift+Tab` move between controls; **Skip to main content** jumps
  past the sidebar.
- `Escape` closes menus, dialogs, and the tour.
- In the tour, `←` and `→` move between steps.
- Status changes are announced to screen readers without moving focus.
- Neyvia follows your system's reduced-motion setting, and
  **Settings → Accessibility** can turn motion down further.

## When something goes wrong

- **The start screen says your workspace hasn't opened**: press
  **Reload workspace**. If it happens again, check that the backend is running.
- **A reply looks stuck**: after a long silence the activity says so. You can
  keep waiting or press **Stop**.
- **A request failed**: the message offers **Connection settings** and
  **Restore message to draft** so nothing you typed is lost.
