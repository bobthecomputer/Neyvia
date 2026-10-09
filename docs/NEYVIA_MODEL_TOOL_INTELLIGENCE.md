# N-E-Y-V-I-A model tool intelligence

## Purpose

This backend layer gives models a small task-specific set of reliable “hands”
without placing the complete tool catalog and every JSON schema in model
context. It joins the existing capability catalog, progressive tools, authored
tools, outbound MCP broker, approval engine, stage scheduler, and receipts.

The visual frontend remains owned by Cursor. The UI should render these
contracts and must not infer availability, approval, provenance, or success.

## Model flow

1. Call `model.tools.compile` with the task, optional roles, artifact media
   types, domains, and a bounded result limit.
2. Use the returned selected tool cards. Search catalog rows are schema-free;
   full schemas are present only for selected tools.
3. For OpenAI Responses, call `model.tools.openai.compile`. Send only its
   `tools` field to the provider and retain `callMap` in N-E-Y-V-I-A.
4. Resolve provider function calls through the retained call map. A friendly
   name never replaces the immutable native call target or original provenance.
5. Execute direct calls through the existing progressive surface, capability
   service, or MCP broker. These surfaces remain the permission authority.
6. Use `model.tools.run` only for an explicit bounded call plan. It stops for
   approval, authentication, invalid plans, repeated non-idempotent calls,
   failed evidence, or call/time/context limits.
7. Read transparent outcome aggregates with `model.tools.feedback`.

## Stable backend commands for Cursor

| Command | Mutation |
|---|---|
| `compile_model_tool_belt_command` | read |
| `compile_openai_tool_belt_command` | read |
| `benchmark_model_tool_routing_command` | read plus retained benchmark receipt |
| `get_model_tool_feedback_command` | read |
| `record_model_tool_feedback_command` | artifact write |
| `run_model_tool_plan_command` | permission-dependent execution |

The same functions are available to models through:

- `model.tools.compile`
- `model.tools.openai.compile`
- `model.tools.benchmark`
- `model.tools.feedback`
- `model.tools.feedback.record`
- `model.tools.run`

## Canonical tool identity

Each selected tool carries:

- a 1–64 character model-facing name;
- a separate human title;
- an immutable `callTarget`;
- optional `boundArguments` such as a capability or authored-tool ID;
- input and output schemas;
- permission and approval hints;
- current availability and the concrete unavailable reason;
- observed reliability and latency;
- provenance: source kind, provider, MCP server, original name/title, version,
  source URL, license, adapter, import time, trust level, and manifest hash.

Imported tools may be renamed for N-E-Y-V-I-A, but the original identity and
source hash are retained. External annotations are routing hints only and never
grant permission.

## Routing policy

- Direct: one call, approval/authentication, side effects, destructive work,
  user-visible messages, native artifacts, or citations.
- Programmatic eligible: bounded read-only filtering, joining, ranking,
  deduplication, aggregation, scanning, or validation.
- Delegated: an MCP or other external adapter executes through its broker.
- Blocked: the adapter or transport is not callable.

“Programmatic” is an eligibility result, not permission to run an unbounded
model loop. The request must still define maximum calls, retries, wall time,
context bytes, evidence, and stop conditions.

## OpenAI Responses integration

`model.tools.openai.compile` emits namespaces, deferred functions, a
`tool_search` entry, strict-compatible schemas when semantics can be preserved,
and a provider call map. Optional object fields become nullable required fields
for strict mode. Unsupported schema constructs are reported and remain
non-strict instead of being silently weakened.

Use:

- `build_responses_request_from_tool_compiler(...)` to build the wire request;
- `resolve_compiled_tool_call(...)` to map a returned namespace/name/arguments
  tuple back to the native call target.

No call map or internal provenance is sent to the provider unless it is already
part of a selected tool description.

## Benchmark and acceptance

`model.tools.benchmark` retains a receipt and measures:

- top-1, top-3, and top-k selection accuracy;
- local routing latency;
- selected context bytes versus the full-schema catalog;
- the exact selected tools for every case.

The default cases cover PDF/OCR, research, Excel, PowerPoint, Unity, authorized
red teaming, model benchmarking, Android testing, student flashcards, and
fashion labels. A 10x claim remains invalid without a retained before/after
baseline on an equivalent catalog and machine.

## Current honest boundary

The backend now compiles and executes tool plans, and exports a valid
OpenAI-model tool contract. The repository does not itself host a complete
OpenAI Responses event loop; deployed Codex/Hermes/provider runtimes must feed
returned function calls through the resolver and existing execution surfaces.
That boundary is explicit so the UI cannot present provider execution as live
unless a runtime has actually connected it.
