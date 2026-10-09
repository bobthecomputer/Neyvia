# Neyvia Operator Guide

This guide is for the person who installs, verifies, and releases Neyvia. For
everyday use of the app, read the [Neyvia guide](NEYVIA_GUIDE.md).

## Launch

| Situation | Command |
| --- | --- |
| Source checkout, web workspace | `npm run neyvia` |
| Installed package | `npm exec -- neyvia` |
| Build the web UI and serve it with the backend | `npm run web:serve` |
| Desktop app while developing | `npm run tauri:dev` |

The launcher waits for the backend health route before it opens `/control`. The
startup screen stays up until the conversation list has loaded; if the page's
code cannot load it shows **Reload workspace** instead of a blank window.

## Before you trust a long run

Do this once on every new machine:

1. Open **Settings → Models & Accounts** and connect at least one provider.
2. Open **Settings → Runtimes & Rooms**. It lists every installed agent runtime,
   what it needs to connect, and the exact model route it uses. Treat `uv` and
   Hermes as required for unattended runs.
3. If Hermes is missing or unhealthy, install or repair it, then confirm it
   reads ready in **Runtimes & Rooms** before you rely on it.
4. Choose the project folder in **Settings → Workspace** (or with the
   **Workspace** control under the message box).
5. Run one small proving task before an unattended long run.

If Hermes is not installed and usable, the machine is not ready for unattended
work.

## First proving task

1. Start **New Orchestration** in the project you want to change.
2. Give a bounded goal, for example: *Tighten the desktop launch path and record
   proof for the changes.*
3. Name the checks that prove it worked, for example:
   `python -m pytest tests -q`, `npm run frontend:build`, or the full desktop
   check `npm run verify:desktop`.
4. Review the plan and approve it. Follow the agents' activity: each reply lists
   its thoughts and tool calls in order, and file edits show their diff.
5. Restart the app mid-run once and confirm the work resumes where it left off.

The first task should show that Neyvia plans and executes without losing the
thread, that proof is visible, that approvals are understandable, and that a
restart does not break continuity.

## Workflow templates

**Workflows** in the sidebar opens **Choose a workflow**. For operators the most
useful templates are:

- **Fix a failing test**: reproduce, find the cause, change the code, and prove
  it passes. A good first proving task.
- **Watch a long run**: check on something running elsewhere and report only
  when it matters.
- **Review my changes**: read the diff and flag real problems before a push or
  deploy.

Loading a template fills in the plan, message, and agent team; edit them before
you start. Reuse your own recipes from the **Saved** tab.

## Proof-bearing mission packs

Some mission packs finish only with verifiable artifacts, never with a
convincing answer alone:

- **Source research** reads several source types and must produce the artifact
  files, a parseable manifest of consulted sources, valid screenshots, and an
  accepted verifier receipt linked to those files. `blocked` is the correct
  result when a browser, sign-in, model, or source reader is unavailable.
- **Controlled AI safety review** runs only against a repository or loopback
  service you are authorized to test, with network egress denied, no model
  calls, one executor, one round, and a ten-minute limit. It requires the
  authorization scope receipt, an HTML control-coverage report, a JSON findings
  ledger, a screenshot of the report, and a verifier receipt that links the HTML
  report. A screenshot alone never passes. Verify the pack with
  `npm run verify:controlled-ai-safety-review`.

External projects can launch the same contracts through the runtime SDK; see
[FLUXIO_RUNTIME_SDK.md](FLUXIO_RUNTIME_SDK.md).

## Working on Neyvia itself

1. Run `npm run tauri:dev`, or `npm run frontend:dev` with the backend running.
2. Validate real behavior against the live backend.
3. To review blocked, resumed, failed, and long-run states, open
   `/control?preview-control=1&fixture=<name>` in the dev server. The fixtures
   are `live_review`, `first_run`, `verification_failure`,
   `approval_resumed`, and `long_run_resumed`.
4. After each meaningful UI pass, run `npm run test:frontend`,
   `npm run frontend:build`, and `python -m pytest tests -q`, or
   `npm run verify:desktop` for the full desktop check.
5. If the pass changes the composer, sidebar, or settings, replay the tour
   (**More → Help: what makes Neyvia different**) and update the [Neyvia guide](NEYVIA_GUIDE.md)
   so both still match the app.

## Release bar

Do not call a machine ready for unattended use unless:

- providers are connected and **Runtimes & Rooms** shows the runtimes you need
  as ready, including Hermes;
- one real proving task has run, with visible and coherent proof;
- a restart mid-run resumed correctly;
- `npm run verify:desktop` passes.
