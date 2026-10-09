# Neyvia runtime audit, July 12, 2026

## Decision

Neyvia should remain a deterministic supervision and proof layer over several
specialist runtimes. A new tool language is not needed. The stable direction is
a versioned, typed protocol with progressive discovery, capability negotiation,
approval metadata, strict argument validation, and durable receipts.

The runtime is not yet honestly verified as the best end-to-end runtime. It is
stronger after this pass, and its local worker reports ready, but the scheduler
currently has no online workstation or NAS executor. Distributed jobs must stay
queued until a worker heartbeat is restored and a clean delegated mission
passes.

## Current evidence

- Active OpenAI defaults use GPT-5.6 Sol. GPT-5.6 Luna is the efficient verifier
  route. Older model IDs remain accepted only for compatibility tests and saved
  missions.
- Ultra is a Neyvia reasoning effort. It compiles into model-supported wire
  efforts and works with models that have different effort ceilings or no
  effort parameter.
- OpenClaw is installed at `2026.6.11`. Its adapter now sends long objectives
  through `--message-file` instead of a multiline Windows command argument.
  The adapter doctor verifies the installed CLI contract before declaring the
  runtime ready.
- Hermes was updated by 140 upstream commits and reports current. Its CLI and
  web build passed, with an unresolved warning that optional Electron packages
  expect Node 22 while the WSL environment currently provides Node 20.19.5.
- OpenCode `1.17.18` remains available as a coding and LSP-oriented worker.
- The Neyvia native tool protocol is version `1.1` and validates schemas before
  policy and execution.
- Seventeen expired managed-process records were reconciled. A second reaper
  scan found zero candidates.
- `worker-doctor` reports `ready` with no issues.
- `architecture-doctor` and `scheduler-doctor` report `warn` because no executor
  heartbeat is online.

## Runtime comparison

| Runtime | Best use | Capability brought into Neyvia | Current gate |
| --- | --- | --- | --- |
| Neyvia native | deterministic control, tools, approvals, receipts, proof | typed progressive tool discovery, preview, screenshots, video digest, resumable NAS transfer | distributed worker heartbeat |
| Hermes | long-horizon autonomous work and broad tools | progressive tool search, MCP change handling, security policy, deliverable workflows, optional video analysis | provider credentials and Node 22 for optional desktop packaging |
| OpenClaw | broad integrations, browser, automation, agent coordination | dynamic tool search and mature browser/tool policy | one clean delegated mission after adapter repair |
| OpenCode | focused coding work | permissions, custom tools, MCP, LSP-oriented execution | route-specific conformance proof |

No single upstream runtime dominates every category. Neyvia's advantage is the
combination: deterministic orchestration owns acceptance, while the selected
worker owns the bounded attempt.

## Tool calling design

Use this common envelope across native and adapter tools:

```json
{
  "protocolVersion": "1.1",
  "tool": "preview.screenshot",
  "arguments": {},
  "capabilitiesRequired": ["browser", "artifact.write"],
  "mutability": "artifact_write",
  "approval": "policy_resolved",
  "receiptRequired": true
}
```

The call lifecycle is:

```text
compact search
-> exact schema load
-> local validation
-> capability and permission check
-> isolated execution
-> typed result
-> proof receipt
```

This provides the useful properties of a language without introducing another
parser, syntax, or model-specific prompt dialect.

## Video strategy

GPT-5.6 Sol accepts images but not video. The reliable workaround is not to show
the model every decoded frame. It is to create a bounded evidence bundle:

1. inspect the video container and streams
2. sample timecoded frames
3. reject blank and near-duplicate samples
4. add scene-change samples
5. create a storyboard and manifest
6. extract audio and transcribe when a configured engine exists
7. let a vision model inspect selected frames with timestamps

The real Neyvia proof recorded an Agent to tutorial to Builder to Agent workflow.
Twelve samples became seven useful storyboard frames. This replaced the earlier
colored test fixture, which was only suitable for deterministic unit testing.

## Product and tutorial audit

The seven-step feature tour was exercised in the live Vite app. It covers the
prompt, modes, storage, preview proof, research proof requirements, keyboard
operation, and reduced motion. Back, Next, Skip, focus behavior, and Escape were
verified, with no browser console errors.

The UI had a real motion-accessibility gap: late-added animations could bypass
component-level reduced-motion rules. A final global reduced-motion guard now
suppresses animations, transitions, delayed transitions, and smooth scrolling
when the operating system requests reduced motion. A duplicate GPT-5.6 Sol
picker entry was also removed.

## Remaining proof gates

1. Restore a persistent workstation or NAS executor heartbeat.
2. Run a clean OpenClaw delegated mission through the repaired message-file
   adapter and collect its runtime, artifact, and verifier receipts.
3. Run a comparable Hermes and OpenCode task under the same contract and budget.
4. Score verified completion, false completion, latency, cost, unnecessary diff
   size, and repair efficiency.
5. Keep the best runtime per task class, not one global winner.
6. Reconcile the legacy desktop/UI static contract suites. The current live
   browser paths pass, but `test_desktop_ui_contract.py` still has 28 obsolete
   assertions, and the wider non-desktop run retains 12 unrelated stale
   Image Playground, Live Review, Solantir-status, and verification-command
   expectations. These are recorded rather than hidden from the handoff.

## Context and Codex import follow-up

The subsequent long-context pass added a durable context ledger, `NEYVIA/1`
orchestration compiler, and safe Codex asset import. The real local Codex audit
found seven personal skills, five system skills, 22 current plugin entries, 13
enabled plugins, 125 plugin skills, 15 plugins with apps, two with MCP server
declarations, and one configured MCP server name. Personal skills were imported
disabled for review; plugin skills remain Codex-linked. No authentication file,
MCP environment value, raw session, or cached executable was imported.

Latest import catalog SHA-256:
`0dc7f237b6966ff7c1e24909dd0a510871e7e50d90352bd247df599ed69932e3`.

## Primary sources

- OpenAI model catalog: <https://developers.openai.com/api/docs/models>
- GPT-5.6 Sol contract: <https://developers.openai.com/api/docs/models/gpt-5.6-sol>
- OpenClaw tools: <https://docs.openclaw.ai/tools>
- Hermes tool search: <https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-search>
- Hermes MCP: <https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp>
- Hermes security: <https://hermes-agent.nousresearch.com/docs/user-guide/security/>
- OpenCode tools: <https://opencode.ai/docs/tools/>
