<!-- Generated from manuals/cl/manuals-next.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# manuals-next

## scripts
CL 1
L manuals-next v1 -- scripts: repeated verified procedures
T t1 json:"{\"type\":\"object\",\"required\":[\"scripts\"]}"
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"object\",\"additionalProperties\":{\"type\":\"string\"}}"
T t4 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"description\":\"Optional restriction on nested tools; never grants authority\"}"
S manuals-next.current:t1=neyvia.manual.compiled()
A neyvia.manual.run(id:str procedure:str inputs?:t2 chapter?:str runId?:str decisions?:t3 evidence?:str scopeTools?:t4) -> t2 ! -- Execute actions and checks; stop at JUDGE; resume same runId with one offered decision
F verify-run "No authored observer check is bound to neyvia.manual.run" -> ask operator blocks:neyvia.manual.run
A neyvia.manual.compile(id:str chapter?:str procedure:str inputs?:t2 minRuns?:2..100) -> t2 ! -- Persist checked executable plan; constant context and decisions specialize; varying branches stay JUDGE
F verify-compile "No authored observer check is bound to neyvia.manual.compile" -> ask operator blocks:neyvia.manual.compile
A neyvia.manual.compiled(id?:str) -> t2 -- List executable plans and stale version flags
F verify-compiled "No authored observer check is bound to neyvia.manual.compiled" -> ask operator blocks:neyvia.manual.compiled
A neyvia.manual.script.run(scriptId:str inputs?:t2 runId?:str decisions?:t3 evidence?:str scopeTools?:t4) -> t2 -- No model call; changed state stops at JUDGE; every effect runs original checks
F verify-script-run "No authored observer check is bound to neyvia.manual.script.run" -> ask operator blocks:neyvia.manual.script.run
P verified-compile(id:str chapter:str procedure:str inputs:t2 minRuns:2..100):artifact=neyvia.manual.compile(chapter:chapter id:id inputs:inputs minRuns:minRuns procedure:procedure) -- Retain exact grounded compile artifact with fresh owner effect checks
V P verified-compile -> script why:"typed manual runner; stops at every judgement"
P verified-run(id:str procedure:str inputs:t2 chapter:str runId:str decisions:t3 scopeTools:t4):artifact=neyvia.manual.run(chapter:chapter decisions:decisions id:id inputs:inputs procedure:procedure runId:runId scopeTools:scopeTools) -- Retain exact grounded run artifact with fresh owner effect checks
V P verified-run -> script why:"typed manual runner; stops at every judgement"
P verified-script-run(scriptId:str inputs:t2 runId:str decisions:t3 scopeTools:t4):artifact=neyvia.manual.script.run(decisions:decisions inputs:inputs runId:runId scopeTools:scopeTools scriptId:scriptId) -- Retain exact grounded script.run artifact with fresh owner effect checks
V P verified-script-run -> script why:"typed manual runner; stops at every judgement"
J script-choice run|recompile:"Is the retained script mapped to the current task and version?" -- Only exact learned input scope and current hashes may run; changed state must retain JUDGE; no implied authority from compilation.
V J script-choice -> human:operator why:"explicit choice required"
X stale script, changed inputs or newer varying decision evidence -> Use manual.run for new inputs; collect checked ordinary runs and compile again.
X changed state before a learned decision -> Inspect the returned JUDGE and explicitly choose an option before resuming.
F Only observed exact input cohorts can specialize; judgement requiring taste stays with the model or Paul.
M manuals-next "neyvia.manual.compile(id,chapter,procedure,inputs,minRuns) consumes .neyvia/manual-runs.jsonl and durable completed runs." src:"authored manual" state:verified
M manuals-next "neyvia.manual.script.run(scriptId,inputs,scopeTools?) uses the same runner; resume with scriptId,runId,decisions." src:"authored manual" state:verified
M manuals-next "Artifacts are data plans, not arbitrary source; modelCalls=0 means this runner made no hidden model request." src:"authored manual" state:verified
M manuals-next "zeroToken is conditional on learned state/input guards; changed state or variable branches return JUDGE." src:"authored manual" state:verified
M manuals-next "CL execution completion requires authored verifiers on every nested mutation; compiled cohorts and model-free reruns retain exact original evidence." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.manual_contracts.validate_structure","grant_agent.manual_contracts.validate_grounding","grant_agent.neyvia_manuals.validate","grant_agent.neyvia_manuals.context","grant_agent.neyvia_manuals.call","grant_agent.proofs_manual_registry_journey.manual_registry_journey"],"claim":"The production manual registry grounds manuals against callable action schemas, refuses a malformed observer schema, blocks an observer outside the caller's nested-tool scope before dispatch, and admits the same observation only when its exact read tool is granted.","id":"p22.manuals.registry-action-admission","impact":["Authored manual validation against the live callable tool registry","Nested observer action admission and caller scope enforcement"],"phase":"post"}

## state
CL 1
L manuals-next v1 -- state: durable handles and deltas
T t1 json:"{\"type\":\"object\",\"required\":[\"manuals\"]}"
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"description\":\"Optional restriction on nested tools; never grants authority\"}"
S manuals-next.current:t1=neyvia.manual.index()
A neyvia.manual.observe(id:str state:str inputs?:t2 chapter?:str scopeTools?:t3 stream?:str previousHandle?:str reset?:bool) -> t2 -- First small result is observed; large result is a handle; later results are diffs
F verify-observe "No authored observer check is bound to neyvia.manual.observe" -> ask operator blocks:neyvia.manual.observe
A neyvia.manual.project(handle:str path?:str offset?:0.. limit?:1..100) -> t2 -- Return bounded selected state; tooLarge requires a deeper path
C neyvia.manual.project selected-projection-handle:neyvia.manual.project(handle:handle limit:limit offset:offset path:path) .handle == handle
C neyvia.manual.project selected-projection-handle:neyvia.manual.project(handle:handle limit:limit offset:offset path:path) .handle == handle
P verified-observe(id:str state:str inputs:t2 chapter:str scopeTools:t3 stream:str previousHandle:str reset:bool):state=neyvia.manual.observe(chapter:chapter id:id inputs:inputs previousHandle:previousHandle reset:reset scopeTools:scopeTools state:state stream:stream) -- Read exact observe state with independent source/artifact verification
V P verified-observe -> script why:"typed manual runner; stops at every judgement"
P verified-project(handle:str path:str offset:0.. limit:1..100):state=neyvia.manual.project(handle:handle limit:limit offset:offset path:path) C selected-projection-handle -- Read exact project state with independent source/artifact verification
V P verified-project -> script why:"typed manual runner; stops at every judgement"
X tooLarge projection -> Choose a deeper JSON Pointer or smaller limit; never infer omitted state.
F Observer source may itself be bounded; handle covers the observed value, not unread source bytes.
M manuals-next "neyvia.manual.observe(id,chapter,state,inputs,stream?,previousHandle?,reset?) reads actual tool state." src:"authored manual" state:verified
M manuals-next "Large observations never paste the whole value; retain handle and use neyvia.manual.project(handle,path,offset,limit)." src:"authored manual" state:verified
M manuals-next "Diffs use JSON Patch add/remove/replace; diffHandle points to an oversized patch. Handles and stream baselines survive restart." src:"authored manual" state:verified
M manuals-next "Observe persists a fresh source-bound handle and stream/diff; project reads an existing immutable handle. Source drift invalidates observation completion while old handles remain immutable." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.manual_contracts.validate_structure","grant_agent.manual_contracts.validate_grounding","grant_agent.neyvia_manuals.validate","grant_agent.neyvia_manuals.context","grant_agent.neyvia_manuals.call","grant_agent.proofs_manual_registry_journey.manual_registry_journey"],"claim":"The production manual registry grounds manuals against callable action schemas, refuses a malformed observer schema, blocks an observer outside the caller's nested-tool scope before dispatch, and admits the same observation only when its exact read tool is granted.","id":"p22.manuals.registry-action-admission","impact":["Authored manual validation against the live callable tool registry","Nested observer action admission and caller scope enforcement"],"phase":"post"}

## versions
CL 1
L manuals-next v1 -- versions: reviewed patches and failure recovery
T t1 json:"{\"type\":\"object\",\"required\":[\"sha256\",\"lineage\"]}"
T t2 json:"{\"type\":\"object\"}"
T t3 [json:"{\"type\":\"object\"}"]#..100
T t4 [str]#1..
T t5 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"description\":\"Optional restriction on nested tools; never grants authority\"}"
S manuals-next.current:t1=neyvia.manual.versions(id:id)
A neyvia.manual.frontier(id:str note:str#1..4000 observed:t2 operations?:t3) -> t2 -- Quarantine notes or bounded JSON Patch operations; never change live source
F verify-frontier "No authored observer check is bound to neyvia.manual.frontier" -> ask operator blocks:neyvia.manual.frontier
A neyvia.manual.patch.apply(id:str patchId:str expectedSha256:str approved:true reviewer:str evidence:t4) -> t2 -- Validate and promote scoped revision with parent hash; no repository source edits
F verify-patch-apply "No authored observer check is bound to neyvia.manual.patch.apply" -> ask operator blocks:neyvia.manual.patch.apply
A neyvia.manual.versions(id:str) -> t2 -- Read current hash, full lineage and demoted procedures
F verify-versions "No authored observer check is bound to neyvia.manual.versions" -> ask operator blocks:neyvia.manual.versions
A neyvia.manual.demote(id:str chapter:str procedure:str reason:str) -> t2 -- Quarantine procedure removal; explicit patch.apply required
F verify-demote "No authored observer check is bound to neyvia.manual.demote" -> ask operator blocks:neyvia.manual.demote
A neyvia.manual.recovery.bind(runId:str chapter:str procedure:str inputs:t2) -> t2 ! -- Bind recipe to hash, exact failure, inputs and original tool restriction
F verify-recovery-bind "No authored observer check is bound to neyvia.manual.recovery.bind" -> ask operator blocks:neyvia.manual.recovery.bind
A neyvia.manual.recover(runId:str recipeId:str scopeTools?:t5) -> t2 ! -- Run a fresh checked recovery; never replay failed effects; unchanged original failure retained
F verify-recover "No authored observer check is bound to neyvia.manual.recover" -> ask operator blocks:neyvia.manual.recover
P quarantine-observation(id:str note:str#1..4000 observed:t2):before=neyvia.manual.versions(id:id); patch=neyvia.manual.frontier(id:id note:note observed:observed) -- Save one observed manual frontier as a quarantined patch without changing the active version
V P quarantine-observation -> script why:"typed manual runner; stops at every judgement"
P quarantine-demotion(chapter:str id:str procedure:str reason:str):before=neyvia.manual.versions(id:id); patch=neyvia.manual.demote(chapter:chapter id:id procedure:procedure reason:reason) -- Quarantine removal of one named obsolete procedure while keeping the current manual active
V P quarantine-demotion -> script why:"typed manual runner; stops at every judgement"
P promote-reviewed-patch(evidence:t4 expectedSha256:str id:str patchId:str reviewer:str):before=neyvia.manual.versions(id:id); J patch-review=approve; promoted=neyvia.manual.patch.apply(approved:true evidence:evidence expectedSha256:expectedSha256 id:id patchId:patchId reviewer:reviewer) -- Apply one explicitly reviewed quarantined patch to this workspace with current base hash and evidence
V P promote-reviewed-patch -> script why:"typed manual runner; stops at every judgement"
P verified-recover(runId:str recipeId:str scopeTools:t5):artifact=neyvia.manual.recover(recipeId:recipeId runId:runId scopeTools:scopeTools) -- Retain exact grounded recover artifact with fresh owner effect checks
V P verified-recover -> script why:"typed manual runner; stops at every judgement"
P verified-recovery-bind(runId:str chapter:str procedure:str inputs:t2):artifact=neyvia.manual.recovery.bind(chapter:chapter inputs:inputs procedure:procedure runId:runId) -- Retain exact grounded recovery.bind artifact with fresh owner effect checks
V P verified-recovery-bind -> script why:"typed manual runner; stops at every judgement"
J patch-review approve|quarantine:"Is the quarantined change supported by current evidence?" -- Promotion requires explicit reviewer, evidence and current base hash; unknown or failing effects stay quarantined.
V J patch-review -> human:operator why:"explicit choice required"
X stale baseSha256 or invalid action schema -> Read current version, revise quarantined patch, rerun grounding; do not bypass CAS.
X unknown situation or verifier failure without a recipe -> Inspect frontier evidence; an explorer/reviewer creates a quarantined patch or bound recovery.
F No automatic explorer/model call or LAYA service integration; frontier responses identify where explicit exploration starts.
M manuals-next "Machine detection returns status=frontier for unknown procedures/states or schema drift and quarantines execution failures with no bound recipe." src:"authored manual" state:verified
M manuals-next "Bind a recipe with neyvia.manual.recovery.bind(runId,chapter,procedure,inputs), then select neyvia.manual.recover(runId,recipeId)." src:"authored manual" state:verified
M manuals-next "Patch operations support chapter-scoped JSON Patch test/add/remove/replace; promotion is explicit and workspace-local." src:"authored manual" state:verified
M manuals-next "Removed procedures stay in parent snapshots and lineage demoted[]; obsolete scripts/recipes cannot run against newer hashes." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.manual_contracts.validate_structure","grant_agent.manual_contracts.validate_grounding","grant_agent.neyvia_manuals.validate","grant_agent.neyvia_manuals.context","grant_agent.neyvia_manuals.call","grant_agent.proofs_manual_registry_journey.manual_registry_journey"],"claim":"The production manual registry grounds manuals against callable action schemas, refuses a malformed observer schema, blocks an observer outside the caller's nested-tool scope before dispatch, and admits the same observation only when its exact read tool is granted.","id":"p22.manuals.registry-action-admission","impact":["Authored manual validation against the live callable tool registry","Nested observer action admission and caller scope enforcement"],"phase":"post"}
