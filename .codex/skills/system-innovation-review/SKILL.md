---
name: system-innovation-review
description: Assess or implement substantial agent-system improvements with one accountable integrator, explicit mechanisms, measured overhead, useful UI, and real user-path verification.
---

# System Innovation Review

Use when the user asks to improve the harness itself or to review a broad implementation for usefulness, simplification, and performance. This is not a mandatory review for every small edit. Preserve the requested stage: a skills review or assessment request does not start a later implementation or release. When implementation is already authorized, carry it through verification without inserting new ceremonial approvals.

## Establish the actual gap

Read the relevant implementation and prior evidence before proposing replacements. Mark each requested capability as absent, partial, integrated but unproven, or verified within a named boundary. A class, UI toggle, or green unit check is not proof of the complete behavior. Check cheap drift-prone facts before relying on older results.

State the user-visible benefit, the mechanism expected to produce it, and the observation that could falsify it. For Neyvia work, read [the system scope and user corrections](references/neyvia-scope.md). Reuse existing skills and architecture where they fit; inspect maintained solutions before building a new runtime or language. Distinguish product primitives from specialist apps that belong in the marketplace.

## Keep one accountable integrator

The current main agent owns the complete capability-to-code-to-UI-to-proof map. Delegate only when authorized and useful, disclose model/effort/count, give disjoint ownership, and close completed children. Additional agents do not replace the integrator's responsibility to resolve conflicting implementations and inspect the joined user journey.

For each part, examine callers, failure paths, authority, state ownership, cancellation, recovery, and resource costs. Identify which decisions are deterministic, which require the model, and which belong to the user. Do not hide a model call, heuristic, fallback, or unsupported capability behind an architectural name.

## Improve value and cost together

Use the existing value-driven-improvement skill when actual optimization is needed. Preserve a real baseline and best verified candidate. Examine repeated context, serialization, tool introductions, full snapshots, redundant model calls, polling, storage growth, and unnecessary process/environment startup. Measure the whole relevant journey and report cold/warm or cached/uncached distinctions where they matter. Smaller files or prompts alone do not prove lower total cost or latency.

Prefer a complete useful mechanism over many disconnected schemas. Simplify or remove demonstrably redundant UI/code within the authorized change after checking dependencies, compatibility, and evidence. Preserve recovery and required controls. File deletion is not a success metric; permanent destruction still requires its actual authority. Retain evidence for rejected experiments.

## Review the human experience after backend work

For every capability, ask whether the user needs to invoke, understand, configure, correct, pause, revoke, or inspect it. Reuse existing controls and Preview first. Add UI only for a real decision or action; make automatic behavior discoverable where necessary. Avoid technical dashboards, duplicated start screens, and settings for implementation details. Keep optional evaluation/rehearsal separate from ordinary completion checks.

Verify applicable discovery, enabled/disabled behavior, correction, persistence, and failure recovery in the real product. Use user-path-validator for product claims and the supported browser tools for rendered interaction; respect the user's Chrome preference when available. Use the smallest relevant build/type/lint and non-Python tests. Skill or config validators are not product evidence.

## Finish at the authorized boundary

In assessment mode, return a prioritized gap map with mechanisms, acceptance gates, costs, dependencies, and unresolved decisions. In implementation mode, make the change, fix in-scope failures, and rerun affected checks. Stop optimizing when the target is verified, the budget ends, or no evidence-backed next step justifies its cost.

For a requested release, retain the exact authorized target and stage; do not ask again for authority already given. Verify the candidate, preserve rollback, publish the intended Git revision, and check the deployed identity and user path. Keep local WIP, committed source, candidates, and NAS current distinct. If the user requested review before implementation or release, complete that review stage first.

Report changed behavior, useful simplifications, measured results, exact proof boundaries, and remaining gaps. Never label the whole programme complete based on one successful fixture.
