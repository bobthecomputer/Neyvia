# Neyvia

Keep the agent you like. Use every other one. One setup.

Neyvia is a local workspace for coding agents, their sessions, and the apps they work on. It brings Claude Code, Codex, OpenCode and Neyvia's own agent into one interface on your PC.

Every coding agent is good at something, and each leaves something missing. Useful features are scattered across tools. You end up maintaining several setups, switching between sessions, and building workarounds to connect them. Neyvia brings those pieces together while keeping the agent and sign-in you already use.

## What you can do

**Work with your agents together.** Choose agents by their real logos, open sessions beside your work, and follow tasks and subagents. The optional Neyvia mod puts its tools and live status inside Claude Code. Neyvia also installs its skills into Codex.

**Run manuals, then reuse what worked.** Manuals are executable procedures with checks and receipts. A verified workspace procedure and its plan can run again with no model calls. When Neyvia needs a model, it records that too. Completion checks make the result inspectable before a task is marked done.

**Give agents a view of apps.** LAYA is a small local model that reads app screens and learns from verified outcomes. Learned browser, routing and visual checks can avoid repeat model calls. The app shows estimated tokens saved; these estimates are not provider-metered savings or a promise about every task.

**Set up Night Shift.** Queue work with dependencies and come back to a morning brief showing completed runs, agent time and token use. Inspect the individual runs when you need the details.

**Browse alongside an agent.** The Browser uses Search-style controls for people and Obscura for agent tasks. Agents can inspect a page, act on observed controls, and check the result. Desktop browser takeover still needs release validation.

**Keep your working tools close.** Files, Notes and PDF support real documents. App Factory can produce a starter app with a live preview and checks. Browse the marketplace, install and remove mods, and use compatibility checks before loading them. Native mobile builds are still being validated.

**Understand usage and choose your surroundings.** Usage shows tokens, cache use, plan windows and API-equivalent prices: a comparison, not your bill. Themes give the workspace different looks. Follow the sun changes supported paired themes through the day, with sunrise and sunset times you control.

## Install

Download the [Windows installer](https://github.com/bobthecomputer/Neyvia/releases/download/neyvia-v0.2.2/Neyvia_0.2.2_x64-setup.exe).

Status: **beta, Windows first**.

For a source checkout, you need a current Node.js, Python 3.11+ and [uv](https://docs.astral.sh/uv/):

```bash
npm ci
uv sync --no-dev
uv run python scripts/launch_neyvia.py
```

This installs the Python runtime dependencies, builds the interface, starts the local service and opens Neyvia in your browser. The first source launch may need a few minutes to prepare Python bytecode. For a headless start, add `--no-browser`; use `--port <free-port>` to select a different local port. The launcher waits up to ten minutes; adjust this with `--startup-timeout <seconds>`. The desktop app uses the same service. Install the coding agents you want to connect and sign into their own accounts; availability depends on the agents and optional components you have installed.

Public source exports contain no bundled user profile, private sessions or raw evidence. Local credentials and workspace data belong to each user's own installation.

## Known limits of this beta

- Windows first.
- 0.1.x installations need a manual reinstall.
- Some automated release checks are still being repaired.

## Learn more

- [Neyvia guide](docs/NEYVIA_GUIDE.md)
- [Operator guide](docs/NEYVIA_OPERATOR_GUIDE.md)
- [Native runtime and tool contract](docs/NEYVIA_NATIVE_RUNTIME.md)
- [Live UI development](docs/LIVE_UI_DEVELOPMENT.md)

## Licence

Neyvia is [MIT licensed](LICENSE), copyright Paul Schmidt de la Brelie.

Third-party components retain their own licences. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing a build.

## Credits

Neyvia stands on work by people we are grateful to. Full license texts and notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- [T3 Code](https://github.com/pingdotgg/t3code) by T3 Tools: the GitHub and pull-request flow we learned from.
- [HyperFrames](https://github.com/heygen-com/hyperframes) by HeyGen: the video studio Neyvia runs for agents.
- [browser-use](https://github.com/browser-use/browser-use) by Gregor Zunic: vendored browser-task code.
- Obscura: the headless browser our agent proofs run on.
- cinetic by Leonxlnx: the motion-design skill behind our film work.
- typesafe-ai skill by TypeSafe AI (MIT).
- [cool-retro-term](https://github.com/Swordfish90/cool-retro-term) by Swordfish90: the look behind our terminal theme (ideas only).
- [fframes](https://github.com/dmtrKovalenko/fframes) by its author (dmtrKovalenko): evaluated for release video.
- [Remotion](https://www.remotion.dev): the React video renderer we looked at for release film work.
- [Tauri](https://tauri.app), [React](https://react.dev), [Vite](https://vite.dev), [Tailwind CSS](https://tailwindcss.com),
  [Motion](https://motion.dev), [Lucide](https://lucide.dev), [Phosphor Icons](https://phosphoricons.com),
  [dnd kit](https://dndkit.com), [react-markdown](https://github.com/remarkjs/react-markdown),
  [Fontsource](https://fontsource.org) (Fraunces, Newsreader, Inter, Geist), [Playwright](https://playwright.dev),
  [Pillow](https://python-pillow.github.io), [websockets](https://github.com/python-websockets/websockets),
  [jsonschema](https://github.com/python-jsonschema/jsonschema), [cryptography](https://github.com/pyca/cryptography),
  and [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).
- The Cua Driver project, pinned for Windows computer use.

Thank you to every maintainer and contributor who makes this work possible.
