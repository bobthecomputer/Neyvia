# Cursor Agent Runtime

Fluxio treats Cursor as a native runtime lane, not as an OpenAI-compatible
provider alias. Use this when a route should run through the local Cursor Agent
CLI and the Cursor subscription model pool.

## Setup

Install Cursor CLI:

```powershell
irm 'https://cursor.com/install?win32=true' | iex
```

On macOS, Linux, or WSL:

```bash
curl https://cursor.com/install -fsS | bash
```

Then authenticate one of these ways:

```bash
agent login
```

or save `CURSOR_API_KEY` in Fluxio provider settings for headless launches.

Check available models:

```bash
agent models
```

Update the CLI:

```bash
agent update
```

## Manual Cursor Agent Runs

From a project terminal inside Cursor or any shell with the CLI on `PATH`:

```bash
agent
```

For a one-shot headless run:

```bash
agent -p --model grok-4-5 --output-format text "Review the current diff and list blockers."
```

For event streaming compatible with Fluxio's bridge:

```bash
agent -p --model composer-2.5 --output-format stream-json --stream-partial-output "Implement the frontend route."
```

The model ids Fluxio normalizes today are:

- `composer-2.5`
- `grok-4-5`

## Fluxio Route Dictation

Example:

```text
GPT-5.6 Sol xhigh for planner, Composer 2.5 fast for frontend executor, GPT-5.6 Sol high for backend executor, Grok 4.5 high for verifier
```

That produces Cursor-backed route rows for `composer-2.5` and `grok-4-5`
with `runtimeId: cursor`, while the planner/backend rows can stay on Codex.

Cursor is useful when the operator wants to test Cursor subscription models in
the same planner/executor/verifier loop. If the verifier rejects a result, the
existing Fluxio lane cycle brings that failure back into the next planner or
executor pass; Cursor does not bypass that control loop.
