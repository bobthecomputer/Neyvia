# CLI Reference

## Commands

- `python -m grant_agent.cli bootstrap`
  - Creates default `config/constitution.json`, `config/personas.json`, `config/skills.json`, and `config/modes.json`.

- `python -m grant_agent.cli run --objective ... --doc ...`
  - Runs the autonomous loop with docs-first preflight.
  - Auto-detects a default verification command when `--verify` is omitted.
  - Supports mode presets via `--mode` (`fast`, `balanced`, `careful`, `creative`, `swarms`, `autopilot`, `deep_run`, `swarm_mega`, `profile`).
  - Key options:
    - `--max-tokens`: context budget.
    - `--max-handoffs`: rollover budget.
    - `--max-runtime-seconds`: runtime budget.
    - `--parallel-agents`: worker branches per iteration.
    - `--merge-policy`: branch merge strategy (`best_score`, `consensus`, `risk_averse`).
    - `--profile`: personalization profile from `config/profiles.json`.
    - `--pause-on-verification-failure`: pause autopilot when checks fail.
    - `--resume-from`: resume from an existing session id.
    - `--checkpoint-every`: checkpoint cadence.
  - Note: docs-first preflight requires readable docs; runs can be blocked if no docs are provided.

- `python -m grant_agent.cli vibe --objective ...`
  - Primary hands-free vibe coding loop.
  - Adds checkpoint snapshots and next-step hints by default.
  - Defaults to profile-aware mode resolution (`--mode profile`) with pause-on-verification-failure enabled.

- `python -m grant_agent.cli vibe-status`
  - Shows latest vibe session objective, autopilot status, checkpoint count, and next suggested actions.

- `python -m grant_agent.cli vibe-continue`
  - Continues the latest vibe session across multiple cycles using latest checkpoints until complete or paused.
  - Also callable from Fluxio desktop Autonomous Run Dashboard.

- `python -m grant_agent.cli profiles`
  - Lists configured personalization profiles and workspace/default resolution rules.
  - Use `--name <profile>` to inspect one resolved profile.

- `python -m grant_agent.cli soak --objective ... --doc ...`
  - Runs multi-cycle autonomous soak validation with checkpoint + artifact checks each cycle.
  - Supports `--profile`, `--merge-policy`, `--cycles`, and `--iterations`.
  - When `--doc` is omitted, soak falls back to default docs (and `README.md` when available).
  - Also callable from Fluxio desktop Autonomous Run Dashboard.

- `python -m grant_agent.cli checkpoints`
  - Lists checkpoints for the latest (or specified) session.

- `python -m grant_agent.cli resume-checkpoint --checkpoint ...`
  - Resumes execution from a specific checkpoint file.

- `python -m grant_agent.cli resume`
  - Automatically resumes from the latest session (or `--session-id`) and continues with stored context.

- `python -m grant_agent.cli memory --query ...`
  - Shows persistent memory snippets across prior runs to support long-horizon continuity.

- `python -m grant_agent.cli suggest-features --paper-file ...`
  - Suggests prioritized product features from pasted paper text.

- `python -m grant_agent.cli list-presets`
  - Lists available challenge presets (`gandalf`, `hackaprompt`).

- `python -m grant_agent.cli demo-run --preset gandalf --objective ...`
  - One-click demo run that executes:
    - Navigator run
    - Training comparison (before/after)
    - Adversarial probe
  - Auto-exports a report bundle with:
    - `proof_report.md`
    - `proof_report_panel.html`
    - comparison and probe JSON files

- `python -m grant_agent.cli demo-suite --objective ...`
  - Runs the demo pipeline across multiple presets and writes a consolidated suite report.
  - Refreshes `proof_dashboard.html` automatically.

- `python -m grant_agent.cli demo-button`
  - Opens a small local GUI button that triggers `demo-run` in one click.

- `python -m grant_agent.cli proof-dashboard --open`
  - Builds a persistent visual dashboard from `.demo_bundles`.
  - Lets you browse bundles, view trend lines, run side-by-side comparator cards, and open proof artifacts.

- `python -m grant_agent.cli next-features`
  - Produces prioritized, metric-driven recommendations for what to improve next.

- `python -m grant_agent.cli inspect`
  - Prints latest state summary.

- `python -m grant_agent.cli replay`
  - Replays timeline events across the latest session lineage.

- `python -m grant_agent.cli search --query ...`
  - Regex search across workspace files for fast investigation.

- `python -m grant_agent.cli story`
  - Prints latest public summary and tweet draft paths/content.

- `python -m grant_agent.cli evaluate`
  - Aggregates metrics across `.agent_runs`.

- `python -m grant_agent.cli export-openai-request --objective ...`
  - Exports a ready-to-send OpenAI Responses API payload with top-k retrieved skills mapped to function tools.
