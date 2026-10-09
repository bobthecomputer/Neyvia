# Public Sharing Guide

This project writes three files to each session folder for lightweight public updates.

## Files

- `run_report.md`: long-form report with progress, checks, and risk notes.
- `tweet_thread.txt`: concise thread draft with numbered posts.
- `public_summary.json`: machine-readable summary for dashboards.

## Suggested posting cadence

- Post one thread per major run.
- Include one screenshot of `run_report.md` and one key metric from `evaluate`.
- Mention one failure mode and one fix each time to show rigor.

## Example command flow

```bash
python -m grant_agent.cli run --objective "Improve autonomous coding loop" --doc "docs/PRD.md"
python -m grant_agent.cli story
python -m grant_agent.cli evaluate
```
