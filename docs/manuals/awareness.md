<!-- Generated from manuals/cl/awareness.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# awareness

## overview
CL 1
L awareness v1 -- Work board (who changes which files), impact map, intent checklist
T t1{claims:json:"{\"type\":\"array\"}" count:int stale:int ..}
T t2 [str]
T t3 [str]#1..100
T t4{claim:{id:str ..} ..}
T t5 json:"{\"type\":\"object\"}"
S awareness.current:t1=neyvia.work.list()
A neyvia.work.list(files?:t2 agent?:str) -> t1 -- Read active claims, overlap/staleness metadata; board grants no filesystem permission
F verify-work-list "No authored observer check is bound to neyvia.work.list" -> ask operator blocks:neyvia.work.list
A neyvia.work.claim(files:t3 intent:str agent?:str chat?:str app?:str) -> t4 ! -- Persist advisory claim and return overlaps; same agent/chat/path set refreshes intent, no requestId field
F verify-work-claim "No authored observer check is bound to neyvia.work.claim" -> ask operator blocks:neyvia.work.claim
A neyvia.work.release(id:str) -> t5 ! -- Remove active claim, retain newest 30 release receipts; does not revert files or stop worker
F verify-work-release "No authored observer check is bound to neyvia.work.release" -> ask operator blocks:neyvia.work.release
A neyvia.impact(paths?:t2 gaps?:bool) -> t5 -- Return command/tool/UI/bridge/test/manual connections and missing wiring; no execution or repair
F verify-impact "No authored observer check is bound to neyvia.impact" -> ask operator blocks:neyvia.impact
A neyvia.intent.checklist(text:str) -> t5 -- Return prompt template and typed checklist schema; model must fill decisions, no hidden model call
F verify-intent-checklist "No authored observer check is bound to neyvia.intent.checklist" -> ask operator blocks:neyvia.intent.checklist
P claim-and-review(files:t3 intent:str):board=neyvia.work.list(); claimed=neyvia.work.claim(files:files intent:intent); impact=neyvia.impact(paths:files); J overlap=release; released=neyvia.work.release(id:claimed.claim.id) -- Claim intended paths, inspect overlap and wiring, release immediately if ownership conflicts
V P claim-and-review -> script why:"typed manual runner; stops at every judgement"
P verify-effect-work-claim(files:t3 intent:str):effect=neyvia.work.claim(files:files intent:intent) -- Verify the actual effect through fresh owning observers
V P verify-effect-work-claim -> script why:"typed manual runner; stops at every judgement"
P verify-effect-work-release(id:str):effect=neyvia.work.release(id:id) -- Verify the actual effect through fresh owning observers
V P verify-effect-work-release -> script why:"typed manual runner; stops at every judgement"
J overlap proceed|release:"Can this claimed work proceed without conflicting with existing owners?" -- Compare returned overlaps against exact file scope; claims are advisory and do not lock files. Coordinate conflicting ownership before proceed; released claim remains historical.
V J overlap -> human:operator why:"explicit choice required"
J intent ready|clarify:"Does the generated checklist schema leave a decision-changing ambiguity?" -- Read original text and preserve corrections; template is not a completed checklist. Resolve target/authority ambiguity before mutation; local formatting choices need no extra approval.
V J intent -> human:operator why:"explicit choice required"
X Claim overlaps another worker -> Inspect overlap paths/intent and coordinate; board is not a lock or authorization
X Claim looks old but worker may still be running -> Check owner evidence; staleness is advisory, never automatically release others
X Impact map reports handler but no UI/bridge/manual -> Inspect named wiring before claiming complete; static matches do not prove runtime
X Checklist returned prompt/schema only -> Have model fill schema from actual asks; do not display template as completed plan
F Runtime-import/dynamic command wiring cannot be established from static impact matching
F No scheduler or conflict-enforcement mechanism on the advisory board
M awareness "Source: src/grant_agent/neyvia_awareness.py; src/grant_agent/neyvia_impact.py; tests/test_neyvia_awareness.py." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.overlaps","grant_agent.proofs_awareness.check_overlap"],"claim":"Case-insensitive paths overlap only at complete folder/file boundaries; absolute and relative forms match at complete suffix/contained component boundaries.","id":"awareness.paths.overlap","impact":["work board claim collisions","filtered work observer"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"A successful new claim persists exactly its agent/chat/intent and normalized unique paths, without changing unrelated claims or release history.","id":"awareness.claim.persisted","impact":[".neyvia/work-board.json","other agents' claimed files"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The same agent/chat/path set refreshes the existing id and original since/files while updating intent and activity timestamp; other claims stay untouched.","id":"awareness.claim.refresh","impact":["claim identity","advisory coordination","stale activity"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The claim receipt includes exactly other agents/chats whose persisted paths overlap the requested paths and includes exactly their shared paths.","id":"awareness.claim.overlaps","impact":["cross-agent coordination","overlap receipts"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.release inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"Release removes exactly the selected active claim and archives it without changing other active entries or the last 29 archived claims; receipt returns removed paths.","id":"awareness.release.persisted","impact":["active claim visibility","recoverable claim history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness.check_list"],"claim":"The observer returns exactly the persisted claims matching files/agent filters, sorted by since, with correct count, stale total and latest five releases.","id":"awareness.list.projection","impact":["work board UI","agent awareness"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim","grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness._view_contract"],"claim":"Age derives from the original since timestamp; stale derives from updatedAt (or since) at the 12-hour boundary. Refresh preserves age and makes an old active claim current.","id":"awareness.claim.staleness","impact":["stale work indicators","claim lineage"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact.find_gaps","grant_agent.proofs_awareness.check_gaps"],"claim":"UI/handler/bridge/Tauri gap categories equal their exact set relations; handler caller review leads distinguish static scripts/tests from absent callers.","id":"awareness.impact.gaps","impact":["impact review","wiring omissions","dead-code decisions"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact._command_row","grant_agent.proofs_awareness.check_command"],"claim":"Each command impact receipt exactly projects UI, handler, bridge, Tauri, tests, manuals and missing ends from the real parsed dependency graph.","id":"awareness.impact.command","impact":["changed-file dependency proof","desktop/UI wiring"],"phase":"post"}
-- @proof {"checkedAt":["src/grant_agent/runtime_capability_inventory.py:build_runtime_capability_inventory -> check_runtime_inventory"],"claim":"Capability inventory exports safe readiness metadata, enabled instruction linkage and honest native activation without raw commands, URLs or environment values","id":"runtime.capability-metadata","impact":["awareness production observations"],"phase":"post"}

## prompt-amplification
CL 1
L awareness v1 -- Preserve rough-prompt asks without model tokens
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"auto\",\"review\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"raw\",\"minimal\",\"full\"]}"
T t4 json:"{\"type\":\"object\",\"properties\":{\"amplification\":{\"type\":\"object\",\"properties\":{\"id\":{\"type\":\"string\"}}}}}"
S awareness.saved:t1=neyvia.prompt.get(id:id)
A neyvia.prompt.amplify(text:str requestId:str sessionId?:str context?:t1 mode?:t2 variant?:t3) -> t4 ! -- Retain original, exact-span checklist and coverage in the card; selected default sends only reversible inline mishear/reference readings; zero model calls
C neyvia.prompt.amplify coverage:neyvia.prompt.get(id:result.amplification.id) .amplification.coverage.ok == true
A neyvia.prompt.get(id:str) -> t4 -- Read saved prompt revision
F verify-get "No authored observer check is bound to neyvia.prompt.get" -> ask operator blocks:neyvia.prompt.get
A neyvia.prompt.edit(id:str revision:int requestId:str text:str) -> t4 ! -- Save exact owner edit; retain evidence without automatic model drafting
F verify-edit "No authored observer check is bound to neyvia.prompt.edit" -> ask operator blocks:neyvia.prompt.edit
C neyvia.prompt.get coverage:neyvia.prompt.get(id:prompt.amplification.id) .amplification.coverage.ok == true
P prepare(text:str requestId:str):prompt=neyvia.prompt.amplify(requestId:requestId text:text) C coverage -- Prepare a lossless reading aid; refuse uncovered sentences
V P prepare -> script why:"typed manual runner; stops at every judgement"
X Original sentence has no exact-span item or proven chatter marker -> Coverage refuses preparation/submission; repair parser without dropping text
X Costly reference has multiple or no candidates -> Review target before submission; context grants no permission
F Conservative spans are reading aids, not proof of semantic interpretation.
F Model extraction and automatic edit-learning are disabled.
F Open files and recent work need bounded supplied context; chat comes from selected broker.
F References outside the bounded chat projection can remain unresolved; a candidate is not an exact target.
M awareness "Original text remains saved verbatim; later corrections affect only named asks." src:"authored manual" state:verified
M awareness "Offsets are Unicode code points. Unknown clauses remain visible context." src:"authored manual" state:verified
M awareness "Minimal is the measured C14f default. Agent text contains only original wording with marked heard/ref readings; inlineEdits holds exact source spans and before/after text for reversal." src:"authored manual" state:verified
M awareness "Checklist, checks, constraints, assumptions, questions and CL context pointers stay in the saved prompt.get record and Paul card; they are not appended on automatic sends." src:"authored manual" state:verified
M awareness "Raw and full remain explicit variant options for audited comparison. Full uses the historical CL reading aid; raw emits the original unchanged." src:"authored manual" state:verified
M awareness "A trailing not remains a visible card assumption and cannot cancel another explicit ask. Consequential ambiguous targets still block sends." src:"authored manual" state:verified
M awareness "An owner card edit appends only fields Paul explicitly changed and answered questions; unchanged card fields never become prompt overhead." src:"authored manual" state:verified
M awareness "C14f five tasks twice: strict intent minimal17/raw16/full14 of22; consumer tokens153139/181006/168734. Small reused panel with four unchanged task prompts is not population or causal gain evidence." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.overlaps","grant_agent.proofs_awareness.check_overlap"],"claim":"Case-insensitive paths overlap only at complete folder/file boundaries; absolute and relative forms match at complete suffix/contained component boundaries.","id":"awareness.paths.overlap","impact":["work board claim collisions","filtered work observer"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"A successful new claim persists exactly its agent/chat/intent and normalized unique paths, without changing unrelated claims or release history.","id":"awareness.claim.persisted","impact":[".neyvia/work-board.json","other agents' claimed files"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The same agent/chat/path set refreshes the existing id and original since/files while updating intent and activity timestamp; other claims stay untouched.","id":"awareness.claim.refresh","impact":["claim identity","advisory coordination","stale activity"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The claim receipt includes exactly other agents/chats whose persisted paths overlap the requested paths and includes exactly their shared paths.","id":"awareness.claim.overlaps","impact":["cross-agent coordination","overlap receipts"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.release inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"Release removes exactly the selected active claim and archives it without changing other active entries or the last 29 archived claims; receipt returns removed paths.","id":"awareness.release.persisted","impact":["active claim visibility","recoverable claim history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness.check_list"],"claim":"The observer returns exactly the persisted claims matching files/agent filters, sorted by since, with correct count, stale total and latest five releases.","id":"awareness.list.projection","impact":["work board UI","agent awareness"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim","grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness._view_contract"],"claim":"Age derives from the original since timestamp; stale derives from updatedAt (or since) at the 12-hour boundary. Refresh preserves age and makes an old active claim current.","id":"awareness.claim.staleness","impact":["stale work indicators","claim lineage"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact.find_gaps","grant_agent.proofs_awareness.check_gaps"],"claim":"UI/handler/bridge/Tauri gap categories equal their exact set relations; handler caller review leads distinguish static scripts/tests from absent callers.","id":"awareness.impact.gaps","impact":["impact review","wiring omissions","dead-code decisions"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact._command_row","grant_agent.proofs_awareness.check_command"],"claim":"Each command impact receipt exactly projects UI, handler, bridge, Tauri, tests, manuals and missing ends from the real parsed dependency graph.","id":"awareness.impact.command","impact":["changed-file dependency proof","desktop/UI wiring"],"phase":"post"}
-- @proof {"checkedAt":["src/grant_agent/runtime_capability_inventory.py:build_runtime_capability_inventory -> check_runtime_inventory"],"claim":"Capability inventory exports safe readiness metadata, enabled instruction linkage and honest native activation without raw commands, URLs or environment values","id":"runtime.capability-metadata","impact":["awareness production observations"],"phase":"post"}

## proofs-e-release
CL 1
L awareness v1 -- Release and capability observations (PROOFS-e)
X Metadata readiness or a scoped proof is mistaken for external execution or a published release -> Inspect the observed boundary and use the owning real activation or publication procedure
F No installer build, installation, publication, download or private signing-key provisioning is claimed.
F Enabled plugin metadata and native instruction linkage do not prove external MCP/plugin execution.
F The impact index proves static command wiring; it does not execute backend or desktop commands.
M awareness "Capability inventory exports safe readiness metadata, enabled instruction linkage and honest native activation without raw commands, URLs or environment values" src:"authored manual" state:verified
M awareness "Self-check: neyvia verify --area proofs-e-release; scoped actual signing, scanner, metadata and static impact actions." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.overlaps","grant_agent.proofs_awareness.check_overlap"],"claim":"Case-insensitive paths overlap only at complete folder/file boundaries; absolute and relative forms match at complete suffix/contained component boundaries.","id":"awareness.paths.overlap","impact":["work board claim collisions","filtered work observer"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"A successful new claim persists exactly its agent/chat/intent and normalized unique paths, without changing unrelated claims or release history.","id":"awareness.claim.persisted","impact":[".neyvia/work-board.json","other agents' claimed files"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The same agent/chat/path set refreshes the existing id and original since/files while updating intent and activity timestamp; other claims stay untouched.","id":"awareness.claim.refresh","impact":["claim identity","advisory coordination","stale activity"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"The claim receipt includes exactly other agents/chats whose persisted paths overlap the requested paths and includes exactly their shared paths.","id":"awareness.claim.overlaps","impact":["cross-agent coordination","overlap receipts"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.release inside _FileLock","grant_agent.proofs_awareness.after"],"claim":"Release removes exactly the selected active claim and archives it without changing other active entries or the last 29 archived claims; receipt returns removed paths.","id":"awareness.release.persisted","impact":["active claim visibility","recoverable claim history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness.check_list"],"claim":"The observer returns exactly the persisted claims matching files/agent filters, sorted by since, with correct count, stale total and latest five releases.","id":"awareness.list.projection","impact":["work board UI","agent awareness"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_awareness.claim","grant_agent.neyvia_awareness.board_list","grant_agent.proofs_awareness._view_contract"],"claim":"Age derives from the original since timestamp; stale derives from updatedAt (or since) at the 12-hour boundary. Refresh preserves age and makes an old active claim current.","id":"awareness.claim.staleness","impact":["stale work indicators","claim lineage"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact.find_gaps","grant_agent.proofs_awareness.check_gaps"],"claim":"UI/handler/bridge/Tauri gap categories equal their exact set relations; handler caller review leads distinguish static scripts/tests from absent callers.","id":"awareness.impact.gaps","impact":["impact review","wiring omissions","dead-code decisions"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.neyvia_impact._command_row","grant_agent.proofs_awareness.check_command"],"claim":"Each command impact receipt exactly projects UI, handler, bridge, Tauri, tests, manuals and missing ends from the real parsed dependency graph.","id":"awareness.impact.command","impact":["changed-file dependency proof","desktop/UI wiring"],"phase":"post"}
-- @proof {"checkedAt":["src/grant_agent/runtime_capability_inventory.py:build_runtime_capability_inventory -> check_runtime_inventory"],"claim":"Capability inventory exports safe readiness metadata, enabled instruction linkage and honest native activation without raw commands, URLs or environment values","id":"runtime.capability-metadata","impact":["awareness production observations"],"phase":"post"}
