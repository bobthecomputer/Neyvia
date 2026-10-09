<!-- Generated from manuals/cl/nightshift.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# nightshift

## board
CL 1
L nightshift v1 -- The Night Shift board in the Canopy: chain tasks, tick with evidence, set the night budget
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"object\",\"properties\":{\"id\":{\"type\":\"string\"},\"title\":{\"type\":\"string\"},\"needs\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}},\"updatedAt\":{\"type\":\"string\"},\"armed\":{\"type\":\"boolean\"},\"status\":{\"type\":\"string\"}},\"required\":[\"id\",\"updatedAt\",\"armed\",\"status\",\"title\",\"needs\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"diff\",\"file\",\"artifact\",\"terminal\",\"browser\",\"mission\",\"replay\",\"builder\",\"accounts\",\"runtime\",\"settings\",\"preview\",\"outputs\",\"perception\"]}"
T t4 [str]
T t5 json:"{\"type\":[\"object\",\"null\"]}"
T t6 json:"{\"type\":\"object\",\"properties\":{\"title\":{\"type\":\"string\"},\"prompt\":{\"type\":\"string\"},\"owner\":{\"type\":\"string\"},\"folder\":{\"type\":\"string\"},\"harness\":{\"type\":\"string\"},\"model\":{\"type\":\"string\"},\"effort\":{\"type\":\"string\"},\"permissionMode\":{\"type\":\"string\"},\"transport\":{\"type\":\"string\"},\"needs\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}},\"requiresGpu\":{\"type\":\"boolean\"},\"limits\":{\"type\":\"object\"},\"completionEvidence\":{\"type\":\"object\"}},\"additionalProperties\":false}"
T t7 json:"{\"type\":[\"integer\",\"null\"],\"minimum\":1}"
T t8 json:"{\"type\":[\"integer\",\"null\"],\"minimum\":1,\"maximum\":100}"
S nightshift.board:t1=neyvia.nightshift.tasks()
S nightshift.morning:t1=neyvia.nightshift.summary()
S nightshift.task:t2=neyvia.nightshift.task(id:id)
A neyvia.pane.show(kind:t3 target:str) -> t1 ! -- Open the Night Shift board (mission pane, target nightshift) on Paul's stage
C neyvia.pane.show board-open:neyvia.state() .pane.kind == "mission"
A neyvia.nightshift.create(id?:str title?:str prompt:str owner?:str folder?:str harness?:str model?:str effort?:str permissionMode?:str transport?:str needs?:t4 requiresGpu?:bool limits?:t1 completionEvidence?:t1) -> t1 -- Store a dormant task; needs are task IDs. Nothing runs until explicitly started.
F verify-nightshift-create "No authored observer check is bound to neyvia.nightshift.create" -> ask operator blocks:neyvia.nightshift.create
A neyvia.nightshift.start(ids:t4) -> t1 -- Arm explicit task IDs under approved prompts/routes, prerequisites and saved resource policy.
F verify-nightshift-start "No authored observer check is bound to neyvia.nightshift.start" -> ask operator blocks:neyvia.nightshift.start
A neyvia.nightshift.tick(id:str evidence:t1) -> t1 -- Complete a task with checked file, commit or its own completed run evidence; releases armed dependents.
F verify-nightshift-tick "No authored observer check is bound to neyvia.nightshift.tick" -> ask operator blocks:neyvia.nightshift.tick
A neyvia.nightshift.resources(maxConcurrent?:int|null maxTaskSeconds?:int|null maxTaskTokens?:int|null maxNightSeconds?:int|null holdAtPlanPercent?:int|null paused?:bool perHarness?:t1 perHarnessBudgets?:t1 gpuReservedFor?:str|null quietGpuHours?:t5) -> t1 -- Read resource policy or request an owner-approved patch. Token limits use reported transport usage.
C neyvia.nightshift.resources plan-hold:neyvia.nightshift.resources() .holdAtPlanPercent == holdPercent
A neyvia.nightshift.summary() -> t1 -- Read morning evidence, blockers, waiting on Paul, measured time and token coverage.
F verify-nightshift-summary "No authored observer check is bound to neyvia.nightshift.summary" -> ask operator blocks:neyvia.nightshift.summary
A neyvia.nightshift.task(id:str) -> t2 -- Observe one saved task before editing or checking its result.
C neyvia.nightshift.task edit-disarmed:neyvia.nightshift.task(id:id) .armed == false
A neyvia.nightshift.edit(id:str patch:t6 expectedUpdatedAt:str) -> t2 -- Edit a dormant unattempted task with its observed updatedAt; disarms it until explicitly started again.
C neyvia.nightshift.edit title-saved:neyvia.nightshift.task(id:id) .title == title
A neyvia.nightshift.reparent(id:str needs:t4 expectedUpdatedAt:str) -> t2 ! -- Replace dormant task prerequisites; missing tasks and dependency cycles are refused; disarms the task.
C neyvia.nightshift.reparent needs-saved:neyvia.nightshift.task(id:id) .needs == needs
C neyvia.state board-open:neyvia.state() .pane.kind == "mission"
C neyvia.nightshift.resources plan-hold:neyvia.nightshift.resources() .holdAtPlanPercent == holdPercent
C neyvia.nightshift.task title-saved:neyvia.nightshift.task(id:id) .title == title
C neyvia.nightshift.task needs-saved:neyvia.nightshift.task(id:id) .needs == needs
C neyvia.nightshift.task edit-disarmed:neyvia.nightshift.task(id:id) .armed == false
P open-board():shown=neyvia.pane.show(kind:"mission" target:"nightshift") C board-open -- Show Paul the Night Shift board
V P open-board -> script why:"typed manual runner; stops at every judgement"
P night-budget(nightSeconds:t7 holdPercent:t8):policy=neyvia.nightshift.resources(holdAtPlanPercent:holdPercent maxNightSeconds:nightSeconds) C plan-hold -- Cap the night's wall time and hold Codex and Claude launches at a plan-limit share
V P night-budget -> script why:"typed manual runner; stops at every judgement"
P edit-task-title(id:str title:str):before=neyvia.nightshift.task(id:id); changed=neyvia.nightshift.edit(expectedUpdatedAt:before.updatedAt id:id patch:{title:title}) C title-saved; after=neyvia.nightshift.task(id:id) C edit-disarmed -- Save the requested dormant task change and independently observe it disarmed
V P edit-task-title -> script why:"typed manual runner; stops at every judgement"
P reparent-task(id:str needs:t4):before=neyvia.nightshift.task(id:id); changed=neyvia.nightshift.reparent(expectedUpdatedAt:before.updatedAt id:id needs:needs) C needs-saved; after=neyvia.nightshift.task(id:id) C edit-disarmed -- Save the requested dormant task change and independently observe it disarmed
V P reparent-task -> script why:"typed manual runner; stops at every judgement"
J arm-now start|hold:"Should these tasks be armed now, with these prompts, routes and the saved budget?" -- Start only when Paul asked for the work to run; a bot start also needs his approval. hold leaves both stored, dormant, visible on the board.
V J arm-now -> human:operator why:"explicit choice required"
X A dependent was created without its prerequisite (needs empty) -> Use nightshift.reparent with current expectedUpdatedAt. Edits disarm dormant tasks and refuse missing dependencies, cycles, running tasks and recorded attempts.
X Codex task that writes files stalls at launch on Windows -> Seen 2 Oct: codex-windows-sandbox-setup.exe stayed running and the run never started (likely a one-time elevated sandbox setup Paul must accept). Stop it from the board; until set up, use read-only prompts that answer in the reply and tick with run evidence
X Start all left a blocked task alone -> Blocked tasks restart one at a time from the board (Start again) after reading why
X Morning card shows a run that did not report tokens -> Its tokens are unknown, not zero; a harness token budget holds further launches until a new night
F The board draws prerequisites as lines on desktop; on phone the columns stack and the lines are hidden
F Plan-limit percentages come from the agents dashboard; Claude reports them only during a turn Neyvia runs
M nightshift "UI: Canopy > Missions pane > Night Shift tab (pane.show kind mission, target nightshift; launcher 'Night Shift'; strip Night Shift > Open the board; Home widget; Grove rail)." src:"authored manual" state:verified
M nightshift "Board: morning card with the growing tree (one leaf per task; full green leaf = done with evidence; amber = running; red = blocked; gold = waiting on Paul), then columns First / Then (n) with lines from each prerequisite." src:"authored manual" state:verified
M nightshift "Task panel: Start / Start again, Stop, Mark done (evidence: agent run, file, commit, or a command Paul vouches for), Block with a reason. Add task and Import TASKS.md never start anything." src:"authored manual" state:verified
M nightshift "Budget panel: pause, hours per night, tasks at once, minutes and tokens per task, per-agent tokens and hours, plan hold (default 70%), keep GPU for dictation, quiet GPU hours." src:"authored manual" state:verified
M nightshift "New night starts a fresh budget period only when nothing runs; history and evidence stay." src:"authored manual" state:verified
M nightshift "Dormant unattempted tasks can be edited or reparented by tools/commands with expectedUpdatedAt. Active, completed and attempted task records stay immutable. Editing disarms the task; explicitly start it again after reviewing the new graph. Select a dormant task and choose Edit task to update its title, prompt and prerequisites. Save changes writes the graph atomically and disarms the task. If someone else changes it, cancel and reopen Edit task to review the current version." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:shapeBoard -> checkedProofsEModel"],"claim":"Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts","id":"nightshift.shapeBoard","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:startable -> checkedProofsEModel"],"claim":"Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded","id":"nightshift.startable","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:evidenceView -> checkedProofsEModel"],"claim":"Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning","id":"nightshift.evidenceView","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:morning -> checkedProofsEModel"],"claim":"Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence","id":"nightshift.morning","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:quietNow -> checkedProofsEModel"],"claim":"Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day","id":"nightshift.quietNow","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_nightshift_journey.mjs","web/src/neyvia/next/NxNightShift.jsx","web/src/neyvia/next/NxNightShiftParts.jsx","web/src/neyvia/next/nxNightShiftApi.js","web/src/neyvia/next/nxNightShiftModel.js","src/grant_agent/neyvia_nightshift.py"],"claim":"On an owned local backend, the mounted production Night Shift saves finite night, concurrency, per-task, plan-hold and GPU quiet-hour limits; a newly added GPU task remains waiting and unarmed, with no run or completion evidence until the owner explicitly starts it.","id":"p22.nightshift.local-policy-ui-journey","impact":["Night Shift resource limits and GPU quiet hours","New tasks wait for explicit start without fake completion evidence"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:treeLayout -> checkedProofsEModel"],"claim":"Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks","id":"nightshift.treeLayout","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyForm -> checkedProofsEModel"],"claim":"Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets","id":"nightshift.policyForm","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyPatch -> checkedProofsEModel"],"claim":"Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget","id":"nightshift.policyPatch","impact":["nightshift frontend model consumers"],"phase":"post"}

## fixcl3-local
CL 1
L nightshift v1 -- Exact retained local admission and supervision
T t1 [str]
T t2 json:"{\"type\":\"object\"}"
A neyvia.nightshift.start(ids:t1) -> t2 -- Exact retained nightshift.start
F verify-neyvia-nightshift-start "No authored observer check is bound to neyvia.nightshift.start" -> ask operator blocks:neyvia.nightshift.start
A neyvia.nightshift.stop(id:str) -> t2 -- Exact retained nightshift.stop
F verify-neyvia-nightshift-stop "No authored observer check is bound to neyvia.nightshift.stop" -> ask operator blocks:neyvia.nightshift.stop
X Fresh owner state differs from this action subject -> Reconcile the specific retained effect; never replay an uncertain launch.
F Admission, arming and local starter bytes do not prove provider execution, rendered preview, device build or installation. Active provider controls require a terminal provider witness.
M nightshift "CL completion re-reads the owner and compares the exact task graph, source hash, retained control or starter bytes." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:shapeBoard -> checkedProofsEModel"],"claim":"Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts","id":"nightshift.shapeBoard","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:startable -> checkedProofsEModel"],"claim":"Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded","id":"nightshift.startable","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:evidenceView -> checkedProofsEModel"],"claim":"Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning","id":"nightshift.evidenceView","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:morning -> checkedProofsEModel"],"claim":"Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence","id":"nightshift.morning","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:quietNow -> checkedProofsEModel"],"claim":"Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day","id":"nightshift.quietNow","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_nightshift_journey.mjs","web/src/neyvia/next/NxNightShift.jsx","web/src/neyvia/next/NxNightShiftParts.jsx","web/src/neyvia/next/nxNightShiftApi.js","web/src/neyvia/next/nxNightShiftModel.js","src/grant_agent/neyvia_nightshift.py"],"claim":"On an owned local backend, the mounted production Night Shift saves finite night, concurrency, per-task, plan-hold and GPU quiet-hour limits; a newly added GPU task remains waiting and unarmed, with no run or completion evidence until the owner explicitly starts it.","id":"p22.nightshift.local-policy-ui-journey","impact":["Night Shift resource limits and GPU quiet hours","New tasks wait for explicit start without fake completion evidence"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:treeLayout -> checkedProofsEModel"],"claim":"Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks","id":"nightshift.treeLayout","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyForm -> checkedProofsEModel"],"claim":"Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets","id":"nightshift.policyForm","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyPatch -> checkedProofsEModel"],"claim":"Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget","id":"nightshift.policyPatch","impact":["nightshift frontend model consumers"],"phase":"post"}

## overview
CL 1
L nightshift v1 -- Night Shift task tree, budgets and morning evidence
T t1 json:"{\"type\":\"object\"}"
T t2 [str]
T t3 json:"{\"type\":[\"object\",\"null\"]}"
S nightshift.board:t1=neyvia.nightshift.tasks()
S nightshift.morning:t1=neyvia.nightshift.summary()
A neyvia.nightshift.tasks() -> t1 -- Read the saved task graph, evidence and launch reasons.
F verify-nightshift-tasks "No authored observer check is bound to neyvia.nightshift.tasks" -> ask operator blocks:neyvia.nightshift.tasks
A neyvia.nightshift.create(id?:str title?:str prompt:str owner?:str folder?:str harness?:str model?:str effort?:str permissionMode?:str transport?:str needs?:t2 requiresGpu?:bool limits?:t1 completionEvidence?:t1) -> t1 -- Store a dormant task; needs are task IDs. Nothing runs until explicitly started.
F verify-nightshift-create "No authored observer check is bound to neyvia.nightshift.create" -> ask operator blocks:neyvia.nightshift.create
A neyvia.nightshift.import(text?:str path?:str folder?:str folders?:t1 defaults?:t1) -> t1 -- Import TASKS.md dormant; source checkboxes do not count as execution evidence.
F verify-nightshift-import "No authored observer check is bound to neyvia.nightshift.import" -> ask operator blocks:neyvia.nightshift.import
A neyvia.nightshift.tick(id:str evidence:t1) -> t1 -- Complete a task with checked file, commit or its own completed run evidence; releases armed dependents.
F verify-nightshift-tick "No authored observer check is bound to neyvia.nightshift.tick" -> ask operator blocks:neyvia.nightshift.tick
A neyvia.nightshift.start(ids:t2) -> t1 -- Arm explicit task IDs under approved prompts/routes, prerequisites and saved resource policy.
F verify-nightshift-start "No authored observer check is bound to neyvia.nightshift.start" -> ask operator blocks:neyvia.nightshift.start
A neyvia.nightshift.stop(id:str) -> t1 ! -- Stop an owned task; active repository lock stays until terminal harness state.
F verify-nightshift-stop "No authored observer check is bound to neyvia.nightshift.stop" -> ask operator blocks:neyvia.nightshift.stop
A neyvia.nightshift.block(id:str reason:str) -> t1 -- Block a non-active task with a reason; completed evidence is immutable.
F verify-nightshift-block "No authored observer check is bound to neyvia.nightshift.block" -> ask operator blocks:neyvia.nightshift.block
A neyvia.nightshift.resources(maxConcurrent?:int|null maxTaskSeconds?:int|null maxTaskTokens?:int|null maxNightSeconds?:int|null holdAtPlanPercent?:int|null paused?:bool perHarness?:t1 perHarnessBudgets?:t1 gpuReservedFor?:str|null quietGpuHours?:t3) -> t1 -- Read resource policy or request an owner-approved patch. Token limits use reported transport usage.
F verify-nightshift-resources "No authored observer check is bound to neyvia.nightshift.resources" -> ask operator blocks:neyvia.nightshift.resources
A neyvia.nightshift.summary() -> t1 -- Read morning evidence, blockers, waiting on Paul, measured time and token coverage.
C neyvia.nightshift.summary usage-known:neyvia.nightshift.summary() .usage.complete == true
A neyvia.nightshift.begin() -> t1 -- Begin a fresh explicit night budget period only with no running tasks; preserves history.
F verify-nightshift-begin "No authored observer check is bound to neyvia.nightshift.begin" -> ask operator blocks:neyvia.nightshift.begin
C neyvia.nightshift.summary usage-known:neyvia.nightshift.summary() .usage.complete == true
P read-morning():morning=neyvia.nightshift.summary() C usage-known; J acceptance -- Observe real evidence and measured usage before reviewing completion
V P read-morning -> script why:"typed manual runner; stops at every judgement"
P store-task(id:str#1.. prompt:str#1.. folder:str#1.. harness:str#1.. model:str#1..):stored=neyvia.nightshift.create(folder:folder harness:harness id:id model:model prompt:prompt) -- Store one exact dormant task and read its saved prerequisites
V P store-task -> script why:"typed manual runner; stops at every judgement"
P import-text(text:str#1.. folder:str#1..):imported=neyvia.nightshift.import(folder:folder text:text) -- Import the selected TASKS.md text as dormant tasks, retaining every prerequisite
V P import-text -> script why:"typed manual runner; stops at every judgement"
P block-task(id:str#1.. reason:str#1..):blocked=neyvia.nightshift.block(id:id reason:reason) -- Block one saved non-active task with an exact reason
V P block-task -> script why:"typed manual runner; stops at every judgement"
P begin-night():night=neyvia.nightshift.begin() -- Start a new night budget period after owner approval and observe its saved ID
V P begin-night -> script why:"typed manual runner; stops at every judgement"
J acceptance accept|inspect:"Do the evidence links satisfy the requested acceptance criteria?" -- A completed CLI run proves execution, not output quality. Inspect file hashes, commits and transcript; unknown usage blocks exact token-budget admission.
V J acceptance -> human:operator why:"explicit choice required"
X Checked imported row treated as done -> Import is dormant; tick with fresh typed file, commit or this task's completed run evidence
X Interrupted task resent after restart -> Inspect its saved run; explicit start creates a new accounted attempt
X Resource hold mistaken for failure -> Read summary task reason; approved policy changes or explicit new night release armed work
F CLI token caps are enforced at reported usage events and may overshoot between events
F GPU policy covers declared requiresGpu tasks; external workloads are not observed
M nightshift "HTTP /api/nightshift and nightshift_<action>_command share SQLite state; desktop commands forward to the persistent authenticated backend" src:"authored manual" state:verified
M nightshift "Bot start, budget changes and beginning a new night require fingerprint-bound owner approval; owner UI uses authenticated commands" src:"authored manual" state:verified
M nightshift "Quiet times are HH:MM local or UTC; equal endpoints mean all day; ASR GPU reservation is the default" src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:shapeBoard -> checkedProofsEModel"],"claim":"Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts","id":"nightshift.shapeBoard","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:startable -> checkedProofsEModel"],"claim":"Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded","id":"nightshift.startable","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:evidenceView -> checkedProofsEModel"],"claim":"Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning","id":"nightshift.evidenceView","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:morning -> checkedProofsEModel"],"claim":"Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence","id":"nightshift.morning","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:quietNow -> checkedProofsEModel"],"claim":"Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day","id":"nightshift.quietNow","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_nightshift_journey.mjs","web/src/neyvia/next/NxNightShift.jsx","web/src/neyvia/next/NxNightShiftParts.jsx","web/src/neyvia/next/nxNightShiftApi.js","web/src/neyvia/next/nxNightShiftModel.js","src/grant_agent/neyvia_nightshift.py"],"claim":"On an owned local backend, the mounted production Night Shift saves finite night, concurrency, per-task, plan-hold and GPU quiet-hour limits; a newly added GPU task remains waiting and unarmed, with no run or completion evidence until the owner explicitly starts it.","id":"p22.nightshift.local-policy-ui-journey","impact":["Night Shift resource limits and GPU quiet hours","New tasks wait for explicit start without fake completion evidence"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:treeLayout -> checkedProofsEModel"],"claim":"Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks","id":"nightshift.treeLayout","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyForm -> checkedProofsEModel"],"claim":"Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets","id":"nightshift.policyForm","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyPatch -> checkedProofsEModel"],"claim":"Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget","id":"nightshift.policyPatch","impact":["nightshift frontend model consumers"],"phase":"post"}

## proofs-e-models
CL 1
L nightshift v1 -- PROOFS-e: production model contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S nightshift.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the most recent verification receipt without invoking production actions again
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-model-proof-receipt():receipt=neyvia.verify.status() C observed -- Read the latest receipt after the production model self-check runner
V P read-model-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X Model transforms are reported as proof of a native app/provider/device effect -> Use the real owning feature procedure and its observed runtime
F Rendered browser/desktop journeys are separate from pure model proof
F Remote device, game editor and provider behavior require their real runtimes
M nightshift "nightshift.shapeBoard: Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts" src:"authored manual" state:verified
M nightshift "nightshift.startable: Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded" src:"authored manual" state:verified
M nightshift "nightshift.evidenceView: Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning" src:"authored manual" state:verified
M nightshift "nightshift.morning: Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence" src:"authored manual" state:verified
M nightshift "nightshift.quietNow: Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day" src:"authored manual" state:verified
M nightshift "nightshift.treeLayout: Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks" src:"authored manual" state:verified
M nightshift "nightshift.policyForm: Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets" src:"authored manual" state:verified
M nightshift "nightshift.policyPatch: Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget" src:"authored manual" state:verified
M nightshift "Startup runner: scripts/proofs-e-models.mjs --root <owned-scratch>; area proofs-e-models checks real model actions and corrupted output refusals" src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:shapeBoard -> checkedProofsEModel"],"claim":"Board excludes missions by default, retains dependency/missing/open/dependent edges and exact state counts","id":"nightshift.shapeBoard","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:startable -> checkedProofsEModel"],"claim":"Only waiting, unarmed agent tasks can be armed; Paul's tasks are always excluded","id":"nightshift.startable","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:evidenceView -> checkedProofsEModel"],"claim":"Evidence retains its actual path, commit, run ids or owner-only command; labels disclose opening meaning","id":"nightshift.evidenceView","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:morning -> checkedProofsEModel"],"claim":"Morning summary counts only completed unreported runs and non-mission tasks; actual evidence links take precedence","id":"nightshift.morning","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:quietNow -> checkedProofsEModel"],"claim":"Quiet windows are start-inclusive/end-exclusive in selected local/UTC clock; midnight wraps and equal endpoints mean all day","id":"nightshift.quietNow","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["scripts/p22_nightshift_journey.mjs","web/src/neyvia/next/NxNightShift.jsx","web/src/neyvia/next/NxNightShiftParts.jsx","web/src/neyvia/next/nxNightShiftApi.js","web/src/neyvia/next/nxNightShiftModel.js","src/grant_agent/neyvia_nightshift.py"],"claim":"On an owned local backend, the mounted production Night Shift saves finite night, concurrency, per-task, plan-hold and GPU quiet-hour limits; a newly added GPU task remains waiting and unarmed, with no run or completion evidence until the owner explicitly starts it.","id":"p22.nightshift.local-policy-ui-journey","impact":["Night Shift resource limits and GPU quiet hours","New tasks wait for explicit start without fake completion evidence"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:treeLayout -> checkedProofsEModel"],"claim":"Every board task gets one measured leaf on its prerequisite branch with exact geometry and alternate sides without invented tasks","id":"nightshift.treeLayout","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyForm -> checkedProofsEModel"],"claim":"Saved policy fields convert measured seconds to one-decimal hours/minutes; toggles retain quiet/GPU/plan hold state and harness budgets","id":"nightshift.policyForm","impact":["nightshift frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxNightShiftModel.js:policyPatch -> checkedProofsEModel"],"claim":"Budget patches convert valid fields to positive integer units and report every invalid count/time/OpenCode token budget","id":"nightshift.policyPatch","impact":["nightshift frontend model consumers"],"phase":"post"}
