# Night Mode Production Profile

Architecture source of truth: [Fluxio Overnight Production Operator Plan](OVERNIGHT_PRODUCTION_OPERATOR_PLAN.md).

Night mode is a production mission profile, not a safe-maintenance-only background loop.

The profile allows Fluxio to run production missions overnight with receipts, bounded repair loops, low resource usage, and truthful blocked/proof-gap states. The NAS remains the controller and storage authority. The PC is an accelerator when awake, especially for browser, build, and heavier verifier work.

## Defaults

- Enabled: `true`
- Window: `01:00` to `06:55` local time
- Autopilot: `true`
- Runtime: `hermes`
- Parallel mission default: `1`
- Repair loops: `1`

## Production Work

- Blocked mission reconciliation
- Small repair loops
- Headless executor work
- Headless verifier work
- Proof compaction
- Morning digest generation

## Deferred Work

- Browser verification when no PC gateway is online
- Full frontend builds while NAS pressure is high
- Destructive Git actions
- Package upgrades without explicit approval
- Commands outside the leased workspace scope

Deferred does not mean failed. The mission must record an explicit proof gap or blocked receipt.

## Required Proof

- Readiness receipt
- Plan receipt
- Execution receipt
- Verification receipt
- Changed-file receipt
- Command receipt
- Artifact receipt or explicit proof gap
- Final morning report row

## Commands

- `get_night_mode_config`
- `configure_night_mode`
- `run_night_mode_now`
- `get_last_night_mode_report`

## Events

- `night-mode://report` emits structured report payloads.
