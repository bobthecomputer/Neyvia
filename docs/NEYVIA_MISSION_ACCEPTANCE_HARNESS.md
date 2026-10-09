# Neyvia Mission Acceptance Harness

This verifier runs five complete mission journeys in a few seconds without
using the network, external accounts, a browser, or paid compute:

1. Research source failure, bounded fallback, evidence, and duplicate suppression.
2. One file transfer with only target existence and size/hash verification.
3. GPU checkpoint preference, capacity and bounded-observation policy,
   paid-start approval, restart reconciliation, idle release, cost evidence,
   and durable recovery.
4. A compiled `NEYVIA/1` mission through the real stage scheduler, including a
   blocked unapproved mutation, an approved retry, verification, and distinct
   durable receipts for both attempts.
5. Authorized purple-team scope, bounded red probe, blue detection evidence,
   remediation, and independent retest.

It uses Neyvia's real orchestration compiler, stage scheduler, outbound MCP
broker, approval receipts, continuity store, retry decisions, GPU policy, and
security scope policy. The MCP providers are explicit in-process fixtures; the
report always says that it is simulated.

Run:

```powershell
.venv\Scripts\python.exe -m grant_agent.mission_acceptance_harness `
  --root .agent_control\mission_acceptance_runtime
```

The durable report is written under:

```text
.agent_control/mission_acceptance_runtime/.agent_control/neyvia/acceptance/
```

Every invocation receives a unique run ID and distinct mission IDs, so the
harness can be rerun against the same durable root without colliding with the
previous run's idempotency receipts. Duplicate suppression is still exercised
inside each run.

Audit installed red/blue-team runtime coverage without executing probes:

```powershell
.venv\Scripts\python.exe -m grant_agent.security_runtime_policy --root .
```

An exit code of `0` means every purple-team phase has at least one currently
execution-ready route. Exit code `2` names the missing phases and lists
installed or catalogued candidates that are not ready.

## Runtime guarantees added with this harness

- Mission continuity read-modify-write cycles are locked across processes.
- Repeated executions of the same compiled plan retain separate stage receipts.
- GPU session-cost, duration, and idle-release policies are enforced.
- GPU close/stop controls are classified as releases rather than inspections;
  rapid or repeatedly unchanged state polls back off, while an expected state
  change can still be observed immediately.
- Active security actions require an explicit target, authorization owner,
  bounded action classes, and target boundaries.
- Production active testing and high-risk action classes cannot execute without
  an action-time approval receipt.
- Red- and blue-team work route as distinct mission types.
- Microsoft Defender is counted as blue-detection evidence only when its
  current executable hash and installed platform version match the pinned
  manifest and health receipt.

This harness is an integration verifier, not a substitute for the final
user-run Thunder Compute or provider-account acceptance steps.
