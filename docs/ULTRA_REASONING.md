# Neyvia Ultra reasoning

Ultra is Neyvia's highest product reasoning effort. It is not a literal provider
API effort value.

When an operator selects **Reasoning → Ultra**, Neyvia compiles an immutable
`fluxio.mission.ultra_reasoning.v1` contract before creating the mission. The
contract records the task diagnostic, chosen topology, worker routes, isolation
policy, verification gate, repair limits, and supported capabilities.

## Current production behavior

- The deterministic controller scores task size, risk, uncertainty, affected
  surfaces, parallelizability, and availability of an executable oracle.
- Narrow, low-risk work uses `direct_verified`.
- Other work uses `investigate_implement_verify`.
- Planner and executor routes use GPT-5.6 Sol at low effort.
- The verifier route uses GPT-5.6 Luna at xhigh effort.
- The operator can override all Ultra workers with `--ultra-worker-effort` or the
  **Ultra worker effort** mission control. Per-role route overrides remain more
  specific than the shared worker value.
- Provider requests receive only supported wire efforts. The product-only value
  `ultra` is compiled away before a provider call.
- Terra is excluded from Ultra delegated routes.
- A Git worktree is mandatory. Ultra blocks before execution when isolation is
  unavailable instead of falling back to the primary workspace.
- Deterministic verification failures cannot be overridden by a model opinion.
- Mission completion remains subject to Neyvia's artifact and verifier proof
  gates.

## Deliberately not simulated

The diagnostic can determine that a task qualifies for competing candidates,
but the current runtime does not yet launch and externally score independent
candidate worktrees. The contract reports this as `eligible: true` and
`enabled: false` rather than treating the existing `parallel_agents` setting as
a candidate tournament.

Likewise, clean-room patch replay is not yet an enforced runtime capability.
Both capability flags stay false until Neyvia can produce reproducible receipts
for them.

## Runtime contract

The mission contract includes:

```text
orchestration.profile                 ultra
orchestration.controller              deterministic
orchestration.selectedTopology        direct_verified | investigate_implement_verify
orchestration.workerPolicy.planner    sol_low
orchestration.workerPolicy.executor   sol_low
orchestration.workerPolicy.verifier   luna_xhigh
orchestration.isolation.required      true
orchestration.verification.hardGate   true
```

## Model-independent effort resolution

Every Ultra route records `requestedEffort`, `effectiveEffort`, `wireEffort`,
the documented `supportedEfforts`, and a resolution strategy.

- exact supported values are passed through
- values above a model's ceiling are clamped down, never up
- providers that do not expose a compatible effort control receive no effort
- unknown custom model IDs stay capability-light and use the provider default
- `ultra` itself is never emitted as a provider parameter

Current documented examples:

- GPT-5.6 Sol, Terra, and Luna: `none`, `low`, `medium`, `high`, `xhigh`, `max`
- older supported OpenAI routes are capability-resolved from their own registered ceiling
- MiniMax and unknown custom routes: no fabricated generic effort parameter

Example:

```powershell
python -m grant_agent.cli mission-start --root . `
  --workspace-id workspace_local --runtime hermes `
  --objective "Implement and verify reconnect support" `
  --reasoning-effort ultra --ultra-worker-effort high
```

The app exposes the resolved topology and policy in the existing evidence rail,
so Ultra remains inspectable without adding a separate dashboard.

Sources: <https://developers.openai.com/api/docs/models>,
<https://developers.openai.com/api/docs/models/gpt-5.6-sol>, and the provider
contracts linked from `agent-provider-conformance`.
