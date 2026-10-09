<!-- Generated from manuals/cl/sidebar.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# sidebar

## overview
CL 1
L sidebar v1 -- Actual agent trees, event lanes and reversible semantic subject folders
T t1 json:"{\"type\":\"object\",\"required\":[\"sessions\",\"subjectFolders\",\"errors\"]}"
T t2 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"maxItems\":100,\"uniqueItems\":true}"
T t3 json:"{\"type\":\"object\",\"properties\":{\"previewId\":{\"type\":\"string\"},\"undoId\":{\"type\":[\"string\",\"null\"]}}}"
S sidebar.current:t1=neyvia.sidebar.state(ids:ids)
A neyvia.sidebar.state(ids?:t2 limit?:1..100 offset?:0.. query?:str) -> t3 -- Observe transcript-based lanes, actual agent subtrees and hover text.
C neyvia.sidebar.state observed:neyvia.sidebar.state(ids:ids) .ok == true
A neyvia.sidebar.preview(ids?:t2 limit?:1..100 threshold?:0.35..0.95) -> t3 -- Preview local semantic subject folders; moves nothing.
F verify-sidebar-preview "No authored observer check is bound to neyvia.sidebar.preview" -> ask operator blocks:neyvia.sidebar.preview
A neyvia.sidebar.confirm(previewId:str confirmed:true groupIds?:t2) -> t3 -- Confirm an unchanged durable sidebar preview. Reuse previewId for retries.
F verify-sidebar-confirm "No authored observer check is bound to neyvia.sidebar.confirm" -> ask operator blocks:neyvia.sidebar.confirm
A neyvia.sidebar.undo(undoId:str) -> t3 ! -- Restore exact prior assignments; preserve later manual changes.
F verify-sidebar-undo "No authored observer check is bound to neyvia.sidebar.undo" -> ask operator blocks:neyvia.sidebar.undo
C neyvia.sidebar.state observed:neyvia.sidebar.state(ids:ids) .ok == true
P preview-subjects(ids:t2):observed=neyvia.sidebar.state(ids:ids) C observed; preview=neyvia.sidebar.preview(ids:ids); J review -- Observe actual conversations and preview semantic subject groups without moving them
V P preview-subjects -> script why:"typed manual runner; stops at every judgement"
P confirm-preview(previewId:str):receipt=neyvia.sidebar.confirm(confirmed:true previewId:previewId) -- Apply a reviewed preview exactly once; stop on stale or active conversations
V P confirm-preview -> script why:"typed manual runner; stops at every judgement"
P undo-grouping(undoId:str):receipt=neyvia.sidebar.undo(undoId:undoId) -- Restore prior assignments while preserving later moves
V P undo-grouping -> script why:"typed manual runner; stops at every judgement"
J review accept|keep:"Do the proposed groups describe the same work?" -- Compare actual prompts and semantic scores; use confirm-preview only after the owner accepts. Never move during preview.
V J review -> human:operator why:"explicit choice required"
X model_unavailable -> Run scripts/setup_t7_embeddings.py in this worktree; bounded pinned model only, no package install
X stale_preview -> Observe again and create a fresh preview; do not retry changed intent as confirmed
X Incomplete transcript -> Keep Other; completeness and read errors are exposed, never guess from title or age
F Collapsed rail and rendered controls belong to the UI handoff
F English embedding model; French semantic quality is unmeasured
F Subject folders are sidebar overlays, not disk directories
M sidebar "Images requires an actual generation event; Quick requires a complete transcript with fewer than three user turns" src:"authored manual" state:verified
M sidebar "CPU only; no runtime network or automatic downloads" src:"authored manual" state:verified
M sidebar "Undo survives restart and never overwrites a later move" src:"authored manual" state:verified
M sidebar "New subject group names use informative words shared by the grouped user prompts; unrelated auto-titles never name a group. Related conversations means no shared phrase was observed, so review the member prompts before confirming." src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:kindOf -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"No-folder lanes reflect observed transcript kind; unknown observations remain Other","id":"proofs-e.shell.kindOf","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:placeSession -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Only observed projects or explicit overrides enter a project; scratch folders remain No folder","id":"proofs-e.shell.placeSession","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:agentSummary -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Nested agents count exactly once with observed running and failed states","id":"proofs-e.shell.agentSummary","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:buildTree -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive","id":"proofs-e.shell.buildTree","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:staleCandidates -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive Default cleanup never authorizes automatic archival.","id":"proofs-e.shell.staleCandidates","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:shouldOfferTidy -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Tidy offers require candidates and the configured size or candidate threshold","id":"proofs-e.shell.shouldOfferTidy","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxOsStore.js:withOverrides -> checkOverrides","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids","id":"proofs-e.shell.overrides","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}

## proofs-e-shell
CL 1
L sidebar v1 -- PROOFS-e shell state and action contracts
T t1{ok:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S sidebar.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the latest verification receipt without repeating shell actions
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-shell-proof-receipt():receipt=neyvia.verify.status() C observed -- Observe the latest shell proof receipt without replaying mutations
V P read-shell-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X A queue or shell state receipt is treated as rendered app proof -> Inspect the owned running UI and actual PDF/output/provider separately
F Rendered shell journeys and PDF loading require owned UI proof
F Provider execution and actual artifact publishing are separate proof boundaries
M sidebar "proofs-e.shell.kindOf: No-folder lanes reflect observed transcript kind; unknown observations remain Other" src:"authored manual" state:verified
M sidebar "proofs-e.shell.placeSession: Only observed projects or explicit overrides enter a project; scratch folders remain No folder" src:"authored manual" state:verified
M sidebar "proofs-e.shell.agentSummary: Nested agents count exactly once with observed running and failed states" src:"authored manual" state:verified
M sidebar "proofs-e.shell.buildTree: Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive" src:"authored manual" state:verified
M sidebar "proofs-e.shell.staleCandidates: Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive" src:"authored manual" state:verified
M sidebar "proofs-e.shell.shouldOfferTidy: Tidy offers require candidates and the configured size or candidate threshold" src:"authored manual" state:verified
M sidebar "proofs-e.shell.overrides: Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids" src:"authored manual" state:verified
M sidebar "Startup runner: scripts/proofs-e-shell.mjs --root <owned-scratch>; area proofs-e-shell checks five composed production journeys and eleven semantic corruptions" src:"authored manual" state:verified
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:kindOf -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"No-folder lanes reflect observed transcript kind; unknown observations remain Other","id":"proofs-e.shell.kindOf","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:placeSession -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Only observed projects or explicit overrides enter a project; scratch folders remain No folder","id":"proofs-e.shell.placeSession","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:agentSummary -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Nested agents count exactly once with observed running and failed states","id":"proofs-e.shell.agentSummary","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:buildTree -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Visible sessions partition into needs-you, pinned, project and transcript lanes; child chats fold and empty projects survive","id":"proofs-e.shell.buildTree","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:staleCandidates -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Archive candidates exceed per-placement age thresholds and require observed safety; protected or dirty sessions survive Default cleanup never authorizes automatic archival.","id":"proofs-e.shell.staleCandidates","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxSidebarModel.js:shouldOfferTidy -> checkSidebar","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Tidy offers require candidates and the configured size or candidate threshold","id":"proofs-e.shell.shouldOfferTidy","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
-- @proof {"checkedAt":["web/src/neyvia/next/nxOsStore.js:withOverrides -> checkOverrides","scripts/proofs-e-shell.mjs:runProofsEShell"],"claim":"Bus overrides reach displayed title, pin, archive and named folder without exposing subject ids","id":"proofs-e.shell.overrides","impact":["Shell bus and rendered sidebar/launcher consumers"],"phase":"post"}
