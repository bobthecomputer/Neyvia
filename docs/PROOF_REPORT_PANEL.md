# Proof Report Panel

The one-click demo workflow exports a stakeholder-ready proof bundle under `.demo_bundles/`.

## Contents

- `proof_report.md`: concise narrative summary.
- `proof_report_panel.html`: visual panel with before/after metrics, probe score, and top findings.
- `training_before.json` / `training_after.json`: comparison snapshots.
- `adversarial_probe.json`: strategy-level probe outcomes.
- `manifest.json`: bundle inventory.

## Generate

```bash
python -m grant_agent.cli demo-run --preset gandalf --objective "Show autonomous hardening loop" --export-zip
python -m grant_agent.cli demo-suite --objective "Show autonomous hardening loop" --export-zip
python -m grant_agent.cli proof-dashboard --open
```

## Use in presentations

- Open `proof_report_panel.html` directly in a browser.
- Share `proof_report.md` for executive notes.
- Attach the `.zip` bundle for reproducibility.
- Use `proof_dashboard.html` to compare bundles side by side and inspect trend lines.
