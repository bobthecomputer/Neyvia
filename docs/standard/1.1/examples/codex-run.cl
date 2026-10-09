CL 1.1
-- Run layer: a Codex run plan. Same sources and content as 1.0 (../../examples/codex-run.cl, ../../examples/today/codex-run.*).

-- L0
L run v2 -- agent runs: plans, claims, goals

-- L1
P run.step_done(step, evidence) G: run.plan().items[step].status == "completed"
A run.plan() -> plan[text status]
A run.plan_update(plan: [{step, status: "pending"|"in_progress"|"completed"}], explanation?) ~ -- at most one in_progress
A work.claim(files: [str], intent) ~ -- never blocks; returns overlapping claims
A work.list(files?: [str]) -> claims[agent files intent since]

-- runtime
run.plan()
R run.plan ok h1
K agent "codex/cl" session="01a0fe77-9b5f" cwd="nx-cl" waiting="docs/standard/READY"
K agent "codex/t20" cwd="nx-t20-browser"
K agent "codex/t21" cwd="nx-t21-limits"
S plan h1 #8 done=2 explanation="Plan 16 order: Claude writes spec and primer first, then implementation, migration, benchmark." [text status]
E "Inventory native tools and manuals: 293 tools, 63 families, 25 manuals" "completed"
E "Provisional o200k token meter and schema graph" "completed"
E "Wait for Claude's spec and primer (docs/standard/READY)" "in_progress"
E "Parser, renderer and validator in src/grant_agent/cl" "pending"
E "do-parser to tool calls through the existing permission gates" "pending"
E "CL <-> JSON Schema/MCP compiler with lossless round trips" "pending"
E "Migrate manuals, T18 perception, T16 tree, receipts and plans to CL" "pending"
E "Benchmark arms a/b/c on GPT-6 Luna and a large model; report" "pending"
R step.1 ok evidence=".agent_control/cl/inventory.json"
R step.2 ok evidence=".agent_control/cl/provisional-meter.json"

-- host
C run.plan_update shown: run.plan().items.text == [s.step for s in plan]
C run.plan_update one-active: [s.status for s in plan].count("in_progress") <= 1
-- P run.step_done: host checks the evidence path exists (files.stat), then applies plan.py apply_op {"op":"update","id":step,"status":"completed"}.
-- K lines come from the work board, ~/.codex/sessions and connected sessions at the moment of each mutation.
-- V routing (which harness or model runs a step) is host policy; it is shown only when it changes who acts.
