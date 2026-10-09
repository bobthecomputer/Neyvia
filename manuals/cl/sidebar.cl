CL 1
L sidebar v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Actual agent trees, event lanes and reversible semantic subject folders"},"proofs-e-shell":{"title":"PROOFS-e shell state and action contracts"}},"clVersion":"1.1","id":"sidebar","kind":"environment","proofs":{"area":"proofs-e-shell","manifests":["config/proofs/proofs-e-shell.json"]},"schema":"neyvia.manual.v1","schemas":{"neyvia.sidebar.confirm":"t1","neyvia.sidebar.preview":"t2","neyvia.sidebar.state":"t3","neyvia.sidebar.undo":"t4","proofs-e-shell.status":"t5"},"tool_metadata":{"neyvia.sidebar.confirm":{"mutability_class":"none"},"neyvia.sidebar.preview":{"mutability_class":"none"},"neyvia.sidebar.state":{"mutability_class":"read"},"neyvia.sidebar.undo":{"mutability_class":"none"},"neyvia.verify.status":{}}}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:kindOf -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"No-folder lanes reflect observed transcript kind; unknown observations remain Other","id":"proofs-e.shell.kindOf","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:placeSession -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Only observed projects or explicit overrides enter a project; scratch folders remain No folder","id":"proofs-e.shell.placeSession","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:agentSummary -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Nested agents count exactly once with observed running and failed states","id":"proofs-e.shell.agentSummary","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:buildTree -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive","id":"proofs-e.shell.buildTree","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:staleCandidates -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive Default cleanup never authorizes automatic archival.","id":"proofs-e.shell.staleCandidates","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:shouldOfferTidy -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Tidy offers require candidates and the configured size or candidate threshold","id":"proofs-e.shell.shouldOfferTidy","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxOsStore.js:withOverrides -> checkOverrides","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids","id":"proofs-e.shell.overrides","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
T t1 json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"confirmed\":{\"const\":true},\"groupIds\":{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}},\"required\":[\"previewId\",\"confirmed\"],\"allOf\":[{\"properties\":{\"previewId\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t2{ids?:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}" limit?:1..100 threshold?:0.35..0.95 ..}
T t3{ids?:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}" limit?:1..100 offset?:0.. query?:str ..}
T t4 json:"{\"type\":\"object\",\"properties\":{\"undoId\":{\"type\":\"string\"}},\"required\":[\"undoId\"],\"allOf\":[{\"properties\":{\"undoId\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t5{..}
T t6{ids:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}"}
T t7 json:"{\"type\":\"object\",\"required\":[\"sessions\",\"subjectFolders\",\"errors\"]}"
T t8 json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}"
T t9{previewId:str}
T t10{undoId:str}
T t11{ok:bool ..}
T t12 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
L sidebar.overview v1 -- Actual agent trees, event lanes and reversible semantic subject folders
-- @record {"chapter":"overview","data":{"args":{"ids":{"$input":"ids"}},"inputs":{"$cl_type":"t6"},"shape":{"$cl_type":"t7"},"tool":"neyvia.sidebar.state"},"key":"current","section":"state"}
S sidebar.current:json:"{\"type\":\"object\",\"required\":[\"sessions\",\"subjectFolders\",\"errors\"]}"=neyvia.sidebar.state(ids:ids)
-- @record {"chapter":"overview","data":{"effect":"Observe transcript-based lanes, actual agent subtrees and hover text.","pre":"Authenticated owner and readable local conversations; confirmation uses an unchanged preview","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.sidebar.state","tool":"neyvia.sidebar.state"},"key":"sidebar.state","section":"actions"}
A neyvia.sidebar.state(ids?:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}" limit?:1..100 offset?:0.. query?:str) -> json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}" -- Observe transcript-based lanes, actual agent subtrees and hover text.
C neyvia.sidebar.state observed:neyvia.sidebar.state(ids:ids) .ok == true
-- @record {"chapter":"overview","data":{"effect":"Preview local semantic subject folders; moves nothing.","pre":"Authenticated owner and readable local conversations; confirmation uses an unchanged preview","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.sidebar.preview","tool":"neyvia.sidebar.preview"},"key":"sidebar.preview","section":"actions"}
A neyvia.sidebar.preview(ids?:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}" limit?:1..100 threshold?:0.35..0.95) -> json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}" -- Preview local semantic subject folders; moves nothing.
F verify-sidebar-preview "No authored observer check is bound to neyvia.sidebar.preview" -> ask operator blocks:neyvia.sidebar.preview
-- @record {"chapter":"overview","data":{"effect":"Confirm an unchanged durable sidebar preview. Reuse previewId for retries.","pre":"Authenticated owner and readable local conversations; confirmation uses an unchanged preview","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.sidebar.confirm","tool":"neyvia.sidebar.confirm"},"key":"sidebar.confirm","section":"actions"}
A neyvia.sidebar.confirm(previewId:str confirmed:true groupIds?:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}") -> json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}" -- Confirm an unchanged durable sidebar preview. Reuse previewId for retries.
F verify-sidebar-confirm "No authored observer check is bound to neyvia.sidebar.confirm" -> ask operator blocks:neyvia.sidebar.confirm
-- @record {"chapter":"overview","data":{"effect":"Restore exact prior assignments; preserve later manual changes.","pre":"Authenticated owner and readable local conversations; confirmation uses an unchanged preview","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.sidebar.undo","tool":"neyvia.sidebar.undo"},"key":"sidebar.undo","section":"actions"}
A neyvia.sidebar.undo(undoId:str) -> json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}" ! -- Restore exact prior assignments; preserve later manual changes.
F verify-sidebar-undo "No authored observer check is bound to neyvia.sidebar.undo" -> ask operator blocks:neyvia.sidebar.undo
-- @record {"chapter":"overview","data":{"args":{"ids":{"$input":"ids"}},"expect":{"op":"eq","path":"ok","value":true},"tool":"neyvia.sidebar.state"},"key":"observed","section":"checks"}
C neyvia.sidebar.state observed:neyvia.sidebar.state(ids:ids) .ok == true
-- @record {"chapter":"overview","data":{"goal":"Observe actual conversations and preview semantic subject groups without moving them","inputs":{"$cl_type":"t6"},"steps":[{"action":"sidebar.state","args":{"ids":{"$input":"ids"}},"check":"observed","save":"observed"},{"action":"sidebar.preview","args":{"ids":{"$input":"ids"}},"save":"preview"},{"judge":"review"}]},"key":"preview-subjects","section":"procedures"}
P preview-subjects(ids:json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}"):observed=neyvia.sidebar.state(ids:ids) C observed; preview=neyvia.sidebar.preview(ids:ids); J review -- Observe actual conversations and preview semantic subject groups without moving them
V P preview-subjects -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Apply a reviewed preview exactly once; stop on stale or active conversations","inputs":{"$cl_type":"t9"},"steps":[{"action":"sidebar.confirm","args":{"confirmed":true,"previewId":{"$input":"previewId"}},"save":"receipt"}]},"key":"confirm-preview","section":"procedures"}
P confirm-preview(previewId:str):receipt=neyvia.sidebar.confirm(confirmed:true previewId:previewId) -- Apply a reviewed preview exactly once; stop on stale or active conversations
V P confirm-preview -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Restore prior assignments while preserving later moves","inputs":{"$cl_type":"t10"},"steps":[{"action":"sidebar.undo","args":{"undoId":{"$input":"undoId"}},"save":"receipt"}]},"key":"undo-grouping","section":"procedures"}
P undo-grouping(undoId:str):receipt=neyvia.sidebar.undo(undoId:undoId) -- Restore prior assignments while preserving later moves
V P undo-grouping -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Compare actual prompts and semantic scores; use confirm-preview only after the owner accepts. Never move during preview.","options":["accept","keep"],"question":"Do the proposed groups describe the same work?"},"key":"review","section":"judge"}
J review accept|keep:"Do the proposed groups describe the same work?" -- Compare actual prompts and semantic scores; use confirm-preview only after the owner accepts. Never move during preview.
V J review -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"model_unavailable","recovery":"Run scripts/setup_t7_embeddings.py in this worktree; bounded pinned model only, no package install"},"key":"0","section":"pitfalls"}
X model_unavailable -> Run scripts/setup_t7_embeddings.py in this worktree; bounded pinned model only, no package install
-- @record {"chapter":"overview","data":{"failure":"stale_preview","recovery":"Observe again and create a fresh preview; do not retry changed intent as confirmed"},"key":"1","section":"pitfalls"}
X stale_preview -> Observe again and create a fresh preview; do not retry changed intent as confirmed
-- @record {"chapter":"overview","data":{"failure":"Incomplete transcript","recovery":"Keep Other; completeness and read errors are exposed, never guess from title or age"},"key":"2","section":"pitfalls"}
X Incomplete transcript -> Keep Other; completeness and read errors are exposed, never guess from title or age
-- @record {"chapter":"overview","data":"Collapsed rail and rendered controls belong to the UI handoff","key":"0","section":"frontier"}
F Collapsed rail and rendered controls belong to the UI handoff
-- @record {"chapter":"overview","data":"English embedding model; French semantic quality is unmeasured","key":"1","section":"frontier"}
F English embedding model; French semantic quality is unmeasured
-- @record {"chapter":"overview","data":"Subject folders are sidebar overlays, not disk directories","key":"2","section":"frontier"}
F Subject folders are sidebar overlays, not disk directories
-- @record {"chapter":"overview","data":"Images requires an actual generation event; Quick requires a complete transcript with fewer than three user turns","key":"0","section":"guidance"}
M sidebar "Images requires an actual generation event; Quick requires a complete transcript with fewer than three user turns" src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"CPU only; no runtime network or automatic downloads","key":"1","section":"guidance"}
M sidebar "CPU only; no runtime network or automatic downloads" src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Undo survives restart and never overwrites a later move","key":"2","section":"guidance"}
M sidebar "Undo survives restart and never overwrites a later move" src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"New subject group names use informative words shared by the grouped user prompts; unrelated auto-titles never name a group. Related conversations means no shared phrase was observed, so review the member prompts before confirming.","key":"3","section":"guidance"}
M sidebar "New subject group names use informative words shared by the grouped user prompts; unrelated auto-titles never name a group. Related conversations means no shared phrase was observed, so review the member prompts before confirming." src:"authored manual" state:verified
L sidebar.proofs-e-shell v1 -- PROOFS-e shell state and action contracts
-- @record {"chapter":"proofs-e-shell","data":{"args":{},"inputs":{"$cl_type":"t5"},"shape":{"$cl_type":"t11"},"tool":"neyvia.verify.status"},"key":"receipt","section":"state"}
S sidebar.receipt:{ok:bool ..}=neyvia.verify.status()
-- @record {"chapter":"proofs-e-shell","data":{"effect":"Read the latest verification receipt without repeating shell actions","pre":"Selected local workspace; read only","returns":{"$cl_type":"t12"},"reversible":true,"schema":"proofs-e-shell.status","tool":"neyvia.verify.status"},"key":"status","section":"actions"}
A neyvia.verify.status() -> json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}" ! -- Read the latest verification receipt without repeating shell actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-shell","data":{"args":{},"expect":{"op":"eq","path":"ok","value":true},"tool":"neyvia.verify.status"},"key":"observed","section":"checks"}
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-shell","data":{"goal":"Observe the latest shell proof receipt without replaying mutations","inputs":{"$cl_type":"t5"},"steps":[{"action":"status","args":{},"check":"observed","save":"receipt"}]},"key":"read-shell-proof-receipt","section":"procedures"}
P read-shell-proof-receipt():receipt=neyvia.verify.status() C observed -- Observe the latest shell proof receipt without replaying mutations
V P read-shell-proof-receipt -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"proofs-e-shell","data":{"failure":"A queue or shell state receipt is treated as rendered app proof","recovery":"Inspect the owned running UI and actual PDF/output/provider separately"},"key":"0","section":"pitfalls"}
X A queue or shell state receipt is treated as rendered app proof -> Inspect the owned running UI and actual PDF/output/provider separately
-- @record {"chapter":"proofs-e-shell","data":"Rendered shell journeys and PDF loading require owned UI proof","key":"0","section":"frontier"}
F Rendered shell journeys and PDF loading require owned UI proof
-- @record {"chapter":"proofs-e-shell","data":"Provider execution and actual artifact publishing are separate proof boundaries","key":"1","section":"frontier"}
F Provider execution and actual artifact publishing are separate proof boundaries
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.kindOf: No-folder lanes reflect observed transcript kind; unknown observations remain Other","key":"0","section":"guidance"}
M sidebar "proofs-e.shell.kindOf: No-folder lanes reflect observed transcript kind; unknown observations remain Other" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.placeSession: Only observed projects or explicit overrides enter a project; scratch folders remain No folder","key":"1","section":"guidance"}
M sidebar "proofs-e.shell.placeSession: Only observed projects or explicit overrides enter a project; scratch folders remain No folder" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.agentSummary: Nested agents count exactly once with observed running and failed states","key":"2","section":"guidance"}
M sidebar "proofs-e.shell.agentSummary: Nested agents count exactly once with observed running and failed states" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.buildTree: Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive","key":"3","section":"guidance"}
M sidebar "proofs-e.shell.buildTree: Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.staleCandidates: Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive","key":"4","section":"guidance"}
M sidebar "proofs-e.shell.staleCandidates: Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.shouldOfferTidy: Tidy offers require candidates and the configured size or candidate threshold","key":"5","section":"guidance"}
M sidebar "proofs-e.shell.shouldOfferTidy: Tidy offers require candidates and the configured size or candidate threshold" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"proofs-e.shell.overrides: Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids","key":"6","section":"guidance"}
M sidebar "proofs-e.shell.overrides: Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-shell","data":"Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions","key":"7","section":"guidance"}
M sidebar "Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions" src:"authored manual" state:verified
