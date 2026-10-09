# Neyvia Native harness capability synthesis

This document separates three things that are easy to blur:

1. **Neyvia Native** — Neyvia's own model loop, behavior compiler, tools, durable state,
   specialist contracts, learning, and proof authority.
2. **Neyvia Hybrid** — the aggregation and orchestration layer that can supervise external
   harnesses without pretending they are Native providers.
3. **External harnesses** — independently installed products with their own sessions,
   transports, licenses, authentication, and limitations.

The aim is not to clone every product surface. It is to absorb the useful mechanism into
Native when Neyvia can own and verify it, while leaving provider- or runtime-specific
behavior in Hybrid.

## Mechanisms absorbed into Native

| Reference characteristic | Native mechanism | Truth boundary |
|---|---|---|
| Codex-style durable sessions, structured execution, MCP, resumability | SQLite parent sessions, hash-chained JSONL events, existing Neyvia MCP gateway, phase and run receipts | JSONL lifecycle streaming is not claimed to be exact provider-token streaming |
| Claude-style hooks, subagents, permissions, receipts | argv-only lifecycle hooks, receipt-bound child sessions, separate read/write authority, proof audit | Hooks currently cover Native lifecycle boundaries; external harness hooks remain external |
| Grok-style worktrees, skills, ACP, custom routes | explicit provider/model routes, executable skill capsules, workspace checkpoints | Independent candidate worktree tournaments and ACP remain frontier items |
| Kimi task lanes and bounded deep/routine work | behavior capsules, per-phase turn budgets, resource modes, per-role specialist limits | A model alias is never silently substituted for another provider route |
| OpenCode provider flexibility and restrained semantic interface | provider-neutral Responses/Chat routes, Native-vs-Hybrid clarity, tonal local-state UI | Availability, authentication, and benchmark eligibility remain separate states |
| Prime Agent goals, heartbeats, schedules, recursive specialists | durable Native goals, milestones, due queries, heartbeats, child contracts | No claim of a background scheduler until an actual worker invokes due goals |
| Pi small composable core, JSONL/RPC, tree sessions | strict JSONL-RPC, progressive tools, parent-child sessions, compact lineage UI | RPC deliberately excludes external effects by default |
| DeepSeek Harness/J-Space interest in structured behavior, modes, plugins, traces | seven-dimensional Behavior Space, versioned capsules, executable skills, append-only trace | Neyvia does not claim to read or alter hidden model activations; this is an executable policy around the model |
| gptme/local-first tool ownership | local workspace, local SQLite state, local proof and checkpoint blobs | Remote services remain explicit configured routes |
| Cursor/Cline/Roo approval and diff-oriented workflows | mutation grants, path-aware checkpoints, final-workspace delta, proof receipts | A checkpoint cannot reverse arbitrary external, device, payment, or shell side effects |
| SWE-agent/OpenHands separation of agent and runtime | behavior/skill plan separated from tools, resource profile, execution, proof, and UI | Full container/Kubernetes substrate remains a Hybrid/runtime concern |

## Native architecture after this pass

```text
operator objective
      │
      ▼
workspace + resource observation
      │
      ▼
Behavior Space compiler ── executable Skill Capsules
      │                         │
      ├─ phases                ├─ instruction hashes
      ├─ behavior vector       ├─ tool scopes
      ├─ specialist routes     ├─ phase bindings
      ├─ resource budget       ├─ checks
      └─ proof gates           └─ evidence gates
      │
      ▼
bounded phase controller
      │
      ├─ lifecycle hooks
      ├─ hash-chained events / JSONL-RPC
      ├─ receipt-bound spawned specialists
      ├─ path-aware content-addressed checkpoints
      └─ durable goal heartbeat
      │
      ▼
final-workspace proof authority
      │
      ├─ delta
      ├─ child/tool/checkpoint receipts
      ├─ deterministic test/build check
      └─ fresh final fingerprint
      │
      ▼
verified usage store + optional operator feedback
```

## Why Behavior Space is the breakthrough candidate

Markdown skills are useful because humans can read and edit them, but text alone leaves too
much to model interpretation. A hard-coded harness mode is enforceable but not sufficiently
malleable. Behavior Space combines both:

- a human-readable skill layer;
- a bounded numerical working-style vector;
- phase-specific objectives and evidence;
- exact tool scopes;
- role/model/effort specialist contracts;
- resource constraints;
- executable checks and proof gates;
- a durable plan hash.

This gives Neyvia a structured space in which behavior can vary without silently changing
safety or proof authority. Evidence-backed learning may make a route more efficient or
proactive, but it cannot lower rigor or verification pressure.

## Remaining high-value frontier

These are not presented as shipped:

1. **Candidate worktree tournament.** Create multiple isolated solutions, run the same frozen
   oracle, promote only the winner, and preserve losing evidence.
2. **Exact resumable phase transport for every provider.** Native phases are mechanical on the
   direct provider path; supervised Codex remains one bounded pass until exact continuation is
   proven.
3. **Full ACP server.** JSONL-RPC and MCP exist, but ACP compatibility has not been certified.
4. **Persistent computation kernel.** Prime-style persistent Python/IPython state could add
   value for data, scientific, and reverse-engineering tasks if sandboxed and receipt-bound.
5. **Signed behavior/skill marketplace.** Capsules need signatures, compatibility declarations,
   test fixtures, rollback, and operator review before cross-user distribution.
6. **Cross-device secret broker.** Pairing avoids moving provider credentials, but opaque
   cross-device delegated authorization still requires platform-specific keychain work.
7. **Active due-goal worker.** The goal store exposes due work; unattended scheduling needs a
   supervised worker, lease, retry, quiet-hours, and notification policy.
8. **Live cross-harness benchmark.** GitHub tests prove contracts, not performance against every
   authenticated harness/model/device combination.
9. **Physical/device sensors.** Serial, ADB, BLE, USB/HID, power, camera, microphone, GPU, and
   thermal adapters need explicit consent, limits, kill switches, and hardware evidence.
10. **Longitudinal user-value learning.** Native must accumulate enough real outcome and feedback
    data before claiming personalized improvement.

## Product rule

Hybrid may expose every useful external option. Native should remain the simplest truthful
expression of the best mechanisms Neyvia can own:

> observe the real task, compile the smallest powerful behavior, execute in bounded phases,
> preserve reversibility and lineage, prove the final state, then learn only from what was
> actually verified.
