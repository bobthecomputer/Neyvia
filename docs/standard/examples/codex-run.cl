CL 1
-- Run layer: a Codex run plan as the agents dashboard sees it. Sources: src/grant_agent/connected_sessions/plan.py
-- (plan_op, apply_op, plan_summary), neyvia_awareness.py (plan.update, work.claim/list), neyvia_intent_plan.py (PLAN_FIELDS).
-- Content: the CL track's own plan on 2 Oct 23:30, from docs/evidence/cl-benchmark.md and .agent_control/cl/.
-- K lines are real sessions read from ~/.codex/sessions (cwd) and from git status of nx-cl.
-- Today's format for the same content: today/codex-run.*

-- L0
L run v1 tools:neyvia -- an agent run: plan, steps, receipts, claims, routing (agents dashboard)

-- L1
T step{text:str status:pending|in_progress|completed=pending active?:str}
T claim{agent:word files:[path] intent:str since:time}
S run.plan:[step] = run.plan(sessionId)
A run.plan(sessionId?:str) -> {items:[step] explanation?:str updatedAt:time}
I run.plan reads:thread.plan
A run.plan_update(plan:[{step:str#1..300 status:pending|in_progress|completed}]#..100 explanation?:str#..300 sessionId?:str#..200) ~ = plan.update(plan explanation sessionId)
I run.plan_update writes:thread.plan emits:plan.changed ui:[composer-checklist,agents-dashboard] undo:run.plan_update(plan:previous.items) -- empty plan clears it
C run.plan_update pre: count(plan.status "in_progress")<=1
C run.plan_update shown: run.plan(sessionId).items.text==plan.step
A work.claim(files:[path]#1..100 intent:str agent?:str chat?:str app?:str) -> {id:id overlaps:[claim]} ~
I work.claim writes:work-board ui:agents-dashboard deps:[agents on overlapping files] undo:work.release(id:result.id) -- never blocks; returns overlaps
C work.claim listed: work.list(files).claims has result.id
A work.list(files?:[path] agent?:str) -> {claims:[claim]}
I work.list reads:work-board

-- L2
J done completed|in_progress: "Is there evidence the step's result exists?" -- completion needs evidence; blocked stays pending with a reason
X two in_progress -> keep the active step; set the other back to pending
Q spec-ready "does docs/standard cover what the parser needs?" -> observe file blocks:step.4 -- READY marks it
V step.1 -> harness:codex done
V step.3 -> harness:claude why:"plan 16 §5: Claude owns the spec and primer"
V step.4 -> harness:codex why:"reference implementation, token meter"
V step.8 -> model:gpt-6-luna why:"small-model arm; a large model is arm c"

-- runtime (real state 23:30)
K agent codex/cl session:01a0fe77-9b5f cwd:nx-cl branch:track/cl helpers:2 waiting:docs/standard/READY
K agent claude/cl-spec writing:docs/standard/ until:READY
K agent codex/t20 cwd:nx-t20-browser
K agent codex/t21 cwd:nx-t21-limits
K claim codex/cl files:[src/grant_agent/cl/,scripts/cl_inventory.py,scripts/cl_token_meter.py,config/cl_benchmark_tasks.json,docs/evidence/cl-benchmark.md] intent:"CL reference implementation"
S run.plan #8 done:2 now:3 explanation:"Plan 16 order: Claude writes spec and primer first, then implementation, migration, benchmark." @h1
E "Inventory native tools and manuals: 293 tools, 63 families, 25 manuals" completed
E "Provisional o200k token meter and schema graph" completed
E "Wait for Claude's spec and primer (docs/standard/READY)" in_progress
E "Parser, renderer and validator in src/grant_agent/cl"
E "do-parser to tool calls through the existing permission gates"
E "CL <-> JSON Schema/MCP compiler with lossless round trips"
E "Migrate manuals, T18 perception, T16 tree, receipts and plans to CL"
E "Benchmark arms a/b/c on GPT-6 Luna and a large model; report"
R step.1 ok evidence:.agent_control/cl/inventory.json
R step.2 ok evidence:.agent_control/cl/provisional-meter.json
