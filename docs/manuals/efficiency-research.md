# Efficiency research ledger (standalone CLI)

## State observers
- `python scripts/efficiency_log.py verify` observes every recorded metric, receipt hash, CI and generated report; it returns JSON and fails closed on disagreement.
- `docs/research/results.jsonl` is the authority; `docs/research/efficiency-log.md` is its readable projection; `coverage.json` documents source discovery.

## Typed actions
- `python scripts/efficiency_log.py append --result <JSON path>` accepts `neyvia.efficiency-result.v1` as defined in `docs/research/schema.md`; it computes values and CIs, preserves previous records and updates the report.
- `python scripts/efficiency_log.py render` reconstructs Markdown only after verifying the ledger and raw receipts.
- `--ledger <path> --report <path>` selects task-local destinations for disposable or separate benchmark ledgers.

## Executable checks
- Require exit code zero and JSON `ok:true` from `verify`; read `scripts/evidence/A4.json` for the exercised successful and adverse CLI journeys.
- A hash mismatch, missing sample, duplicate ID, unknown schema, literal measured number or stale report must produce a nonzero exit; no rejected append may change the ledger.

## Procedures
- Write and retain the real benchmark receipt; create a result specification with actual routes, tasks/repetitions, calculation pointers and limits; append; verify in a fresh process; inspect the generated study paragraph.
- After interrupted report generation, run `render`, then `verify`; treat the ledger as authoritative.

## Judgement points
- Use `raw-verified` only for actual case/event/execution receipts; use `aggregate-only` for a summary without independent sample recomputation, and `unverified` for unsupported prose or unavailable results.
- Choose the independent statistical unit before measuring; keep repeated tasks in the same bootstrap cluster. State why an interval is unavailable instead of inventing one.

## Pitfalls
- Cached input is part of total input for Codex; never add it a second time. Preserve separately charged cache writes where the provider reports them.
- A warm exact-key replay is not a novel task or warm model benchmark; include corrections and setup when comparing total workflow cost.
- An abandoned writer can leave a lock; inspect its recorded process before removing a stale task-local lock.

## Frontier
- This is a local benchmark/reporting CLI, callable by existing terminal tools; it adds no UI/backend/desktop command and does not launch models or publish releases.
- Historical receipt validation does not establish independent model routing, generalization, physical microphone performance, visual quality or production promotion.
