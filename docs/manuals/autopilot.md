<!-- Generated from manuals/cl/autopilot.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# autopilot

## fixcl3-local
CL 1
L autopilot v1 -- Exact retained local admission and supervision
T t1 json:"{\"type\":\"object\"}"
A neyvia.autopilot.stop(runId:str) -> t1 -- Exact retained autopilot.stop
C neyvia.autopilot.stop autopilot-stop-observed:neyvia.autopilot.get(runId:runId) .run.status == "stopped"
C neyvia.autopilot.get autopilot-stop-observed:neyvia.autopilot.get(runId:runId) .run.status == "stopped"
P retain-autopilot-stop(runId:str):effect=neyvia.autopilot.stop(runId:runId) C autopilot-stop-observed -- Requested local autopilot.stop matches fresh owner observation
V P retain-autopilot-stop -> script why:"typed manual runner; stops at every judgement"
X Fresh owner state differs from this action subject -> Reconcile the specific retained effect; never replay an uncertain launch.
F Admission, arming and local starter bytes do not prove provider execution, rendered preview, device build or installation. Active provider controls require a terminal provider witness.
M autopilot "CL completion re-reads the owner and compares the exact task graph, source hash, retained control or starter bytes." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeTools -> checkedProofsEModel"],"claim":"Unknown scopes are read-only; edit adds only workspace.write","id":"autopilot.scopeTools","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeOf -> checkedProofsEModel"],"claim":"Only a named CAS workspace.write grants edit scope","id":"autopilot.scopeOf","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:attributeCalls -> checkedProofsEModel"],"claim":"Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order","id":"autopilot.attributeCalls","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:shapeRun -> checkedProofsEModel"],"claim":"Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations","id":"autopilot.shapeRun","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:checkLine -> checkedProofsEModel"],"claim":"Final verification text names the real tool, target, observed path and exact operation/value","id":"autopilot.checkLine","impact":["autopilot frontend model consumers"],"phase":"post"}

## fixcl4-real
CL 1
L autopilot v1 -- Actual provider and manual completion
T t1 [str]#1..100
T t2{project:str url:str clSource?:str native?:json:"{\"type\":\"object\"}" steps?:[json:"{\"type\":\"object\"}"]}
T t3 json:"{\"type\":\"object\"}"
T t4 [str]
A neyvia.autopilot.start(requestId:str#1..160 text:str#1..40000 sessionId?:str scopeTools:t1 background?:bool efficiency?:bool appGoal?:t2 maxModelCalls?:1..50 maxSeconds?:10..3600) -> t3 -- Complete an intent through scoped manuals and executable checks; models only decide branches. Retry requestId safely.
F verify-autopilot-start "No authored observer check is bound to neyvia.autopilot.start" -> ask operator blocks:neyvia.autopilot.start
A neyvia.autopilot.resume(runId:str background?:bool scopeTools?:t4) -> t3 -- Continue a stopped run without replaying completed or uncertain effects; original scope cannot widen.
F verify-autopilot-resume "No authored observer check is bound to neyvia.autopilot.resume" -> ask operator blocks:neyvia.autopilot.resume
P verify-autopilot-start(requestId:str#1..160 text:str#1..40000 sessionId:str scopeTools:t1 background:bool efficiency:bool appGoal:t2 maxModelCalls:1..50 maxSeconds:10..3600):effect=neyvia.autopilot.start(appGoal:appGoal background:background efficiency:efficiency maxModelCalls:maxModelCalls maxSeconds:maxSeconds requestId:requestId scopeTools:scopeTools sessionId:sessionId text:text) -- Complete an intent through scoped manuals and executable checks; models only decide branches. Retry requestId safely.
V P verify-autopilot-start -> script why:"typed manual runner; stops at every judgement"
P verify-autopilot-resume(runId:str background:bool scopeTools:t4):effect=neyvia.autopilot.resume(background:background runId:runId scopeTools:scopeTools) -- Continue a stopped run without replaying completed or uncertain effects; original scope cannot widen.
V P verify-autopilot-resume -> script why:"typed manual runner; stops at every judgement"
X A queued admission or provider call is called completed -> Read the retained owner and require actual terminal provider/manual receipts and fresh acceptance.
F Selected provider unavailability or model refusal is retained as a failure; no provider substitution or fabricated output.
M autopilot "Reuse the exact request identity and original scope. Completed resumes verify retained effects without replaying completed work." src:"authored manual" state:verified
M autopilot "Select NEYVIA_AUTOPILOT_SMALL_MODEL explicitly for this process before starting a run. Supported routes are gpt-6-luna and gpt-6.1-sol; an unknown route fails before inference. Provider receipts retain the actual model and token usage." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeTools -> checkedProofsEModel"],"claim":"Unknown scopes are read-only; edit adds only workspace.write","id":"autopilot.scopeTools","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeOf -> checkedProofsEModel"],"claim":"Only a named CAS workspace.write grants edit scope","id":"autopilot.scopeOf","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:attributeCalls -> checkedProofsEModel"],"claim":"Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order","id":"autopilot.attributeCalls","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:shapeRun -> checkedProofsEModel"],"claim":"Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations","id":"autopilot.shapeRun","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:checkLine -> checkedProofsEModel"],"claim":"Final verification text names the real tool, target, observed path and exact operation/value","id":"autopilot.checkLine","impact":["autopilot frontend model consumers"],"phase":"post"}

## overview
CL 1
L autopilot v1 -- Autopilot: intent to verified checklist
T t1 json:"{\"type\":\"object\",\"required\":[\"run\"]}"
T t2 json:"{\"type\":\"object\"}"
T t3 [str]#1..100
T t4{project:str url:str clSource?:str native?:json:"{\"type\":\"object\"}" steps?:[json:"{\"type\":\"object\"}"]}
T t5 [str]
S autopilot.run:t1=neyvia.autopilot.get(runId:runId)
A neyvia.autopilot.get(runId:str) -> t2 -- Read authoritative durable receipts
C neyvia.autopilot.get completed:neyvia.autopilot.get(runId:runId) .run.status == "completed"
A neyvia.autopilot.start(requestId:str#1..160 text:str#1..40000 sessionId?:str scopeTools:t3 background?:bool efficiency?:bool appGoal?:t4 maxModelCalls?:1..50 maxSeconds?:10..3600) -> t2 ! -- Run synchronously through the Native gateway or start background owner HTTP; every ask gets checked receipts
F verify-start "No authored observer check is bound to neyvia.autopilot.start" -> ask operator blocks:neyvia.autopilot.start
A neyvia.autopilot.list() -> t2 -- Read durable run states
F verify-list "No authored observer check is bound to neyvia.autopilot.list" -> ask operator blocks:neyvia.autopilot.list
A neyvia.autopilot.stop(runId:str) -> t2 ! -- Stop at next action boundary; preserve newest progress and source bytes
F verify-stop "No authored observer check is bound to neyvia.autopilot.stop" -> ask operator blocks:neyvia.autopilot.stop
A neyvia.autopilot.resume(runId:str background?:bool scopeTools?:t5) -> t2 -- Continue retained progress; completed children are never repeated
F verify-resume "No authored observer check is bound to neyvia.autopilot.resume" -> ask operator blocks:neyvia.autopilot.resume
C neyvia.autopilot.get completed:neyvia.autopilot.get(runId:runId) .run.status == "completed"
P verify-run(runId:str):run=neyvia.autopilot.get(runId:runId) C completed -- Verify that all autopilot asks have executable completion receipts
V P verify-run -> script why:"typed manual runner; stops at every judgement"
X Interrupted effect or verifier failure -> Inspect receipt and reconcile; never restart the same write as a new request.
X Nesting start inside manual.run -> Call autopilot.start directly through the owning gateway; the controller owns manual execution locks.
F Automatic execution currently supports local observations and saved-source CAS text edits; external/irreversible actions require separate approval.
F Quarantined mapping patches are proposed by exploration, never promoted by autopilot.
M autopilot "Start with exact scopeTools; scope restricts caller authority and grants nothing." src:"authored manual" state:verified
M autopilot "Luna selects manual procedures and decides explicit JUDGE points; explicit gpt-6.1-sol handles disagreement/frontier." src:"authored manual" state:verified
M autopilot "Compiled scripts are reused only for current hashes and identical learned inputs; changed guards return to JUDGE." src:"authored manual" state:verified
M autopilot "Background runs belong to owner HTTP POST /api/ui/autopilot; tool starts run synchronously." src:"authored manual" state:verified
M autopilot "Same requestId retries return retained state. Stop is cooperative at the next action; poll get/list for proof." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeTools -> checkedProofsEModel"],"claim":"Unknown scopes are read-only; edit adds only workspace.write","id":"autopilot.scopeTools","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeOf -> checkedProofsEModel"],"claim":"Only a named CAS workspace.write grants edit scope","id":"autopilot.scopeOf","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:attributeCalls -> checkedProofsEModel"],"claim":"Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order","id":"autopilot.attributeCalls","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:shapeRun -> checkedProofsEModel"],"claim":"Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations","id":"autopilot.shapeRun","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:checkLine -> checkedProofsEModel"],"claim":"Final verification text names the real tool, target, observed path and exact operation/value","id":"autopilot.checkLine","impact":["autopilot frontend model consumers"],"phase":"post"}

## proofs-e-models
CL 1
L autopilot v1 -- PROOFS-e: production model contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S autopilot.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the most recent verification receipt without invoking production actions again
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-model-proof-receipt():receipt=neyvia.verify.status() C observed -- Read the latest receipt after the production model self-check runner
V P read-model-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X Model transforms are reported as proof of a native app/provider/device effect -> Use the real owning feature procedure and its observed runtime
F Rendered browser/desktop journeys are separate from pure model proof
F Remote device, game editor and provider behavior require their real runtimes
M autopilot "autopilot.scopeTools: Unknown scopes are read-only; edit adds only workspace.write" src:"authored manual" state:verified
M autopilot "autopilot.scopeOf: Only a named CAS workspace.write grants edit scope" src:"authored manual" state:verified
M autopilot "autopilot.attributeCalls: Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order" src:"authored manual" state:verified
M autopilot "autopilot.shapeRun: Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations" src:"authored manual" state:verified
M autopilot "autopilot.checkLine: Final verification text names the real tool, target, observed path and exact operation/value" src:"authored manual" state:verified
M autopilot "Startup runner: scripts/proofs-e-models.mjs --root <owned-scratch>; area proofs-e-models checks real model actions and corrupted output refusals" src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeTools -> checkedProofsEModel"],"claim":"Unknown scopes are read-only; edit adds only workspace.write","id":"autopilot.scopeTools","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:scopeOf -> checkedProofsEModel"],"claim":"Only a named CAS workspace.write grants edit scope","id":"autopilot.scopeOf","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:attributeCalls -> checkedProofsEModel"],"claim":"Every observed model call stays visible once, with its measured tokens, and judgement/frontier calls follow item order","id":"autopilot.attributeCalls","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:shapeRun -> checkedProofsEModel"],"claim":"Item routes preserve receipts; completed manual/script counts and total tokens come only from durable observations","id":"autopilot.shapeRun","impact":["autopilot frontend model consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxAutopilotModel.js:checkLine -> checkedProofsEModel"],"claim":"Final verification text names the real tool, target, observed path and exact operation/value","id":"autopilot.checkLine","impact":["autopilot frontend model consumers"],"phase":"post"}
