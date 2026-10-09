# demo_runner

Provides backend / demo_runner in Neyvia.

- **Public API:** `append_red_team_escalation_history`, `build_difficulty_escalation`, `build_red_team_escalation_audit`, `build_red_team_escalation_trend`, `build_red_team_history_row`, `compare_training`, `export_report_bundle`, `load_red_team_escalation_history`, `normalize_red_team_pressure`, `redact_probe_payload_for_export`, `run_adversarial_probe`, `summarize_run`, `top_findings`, `utc_stamp`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `desktop.demo.comparison`, `desktop.demo.export`, `desktop.demo.probe`.
- **Dependencies:** [backend.challenge_presets](../backend.challenge_presets/README.md), [backend.proofs_b_desktop](../backend.proofs_b_desktop/README.md).
- **Owner:** Neyvia / neyvia.
- **Files:** [src/grant_agent/demo_runner.py](../../src/grant_agent/demo_runner.py).
