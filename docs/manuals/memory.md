<!-- Generated from manuals/cl/memory.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# memory

## cue-memory
CL 1
L memory v1 -- Private cue memory and fresh lifecycle proof
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"fact\",\"preference\",\"procedure\",\"pitfall\"]}"
T t3 json:"{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"intent\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"app\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"layer\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"files\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"task\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"entities\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12}}}"
T t4 json:"{\"type\":\"string\",\"enum\":[\"local\",\"provider\"]}"
T t5{memory:{id:str revision:int status:str content?:str ..} generation:int ..}
T t6 json:"{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"intent\":{\"type\":\"string\"},\"app\":{\"type\":\"string\"},\"layer\":{\"type\":\"string\"},\"files\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"task\":{\"type\":\"string\"},\"entities\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12}}}"
T t7 str ~"^[a-fA-F0-9]{64}$"
T t8 json:"{\"type\":\"string\",\"enum\":[\"auto\",\"powershell\",\"python\",\"bash\",\"cmd\"]}"
T t9 json:"{\"type\":\"string\",\"enum\":[\"fact\",\"preference\",\"procedure\",\"pitfall\"],\"default\":\"fact\"}"
T t10 json:"{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"intent\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"app\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"layer\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"files\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"task\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12},\"entities\":{\"type\":\"array\",\"items\":{\"type\":\"string\",\"maxLength\":160},\"maxItems\":12}},\"default\":{\"intent\":[\"memory\"]}}"
T t11 json:"{\"type\":[\"string\",\"null\"],\"default\":null}"
T t12 json:"{\"type\":\"string\",\"enum\":[\"local\",\"provider\"],\"default\":\"local\"}"
S memory.scope:t1=neyvia.memory.list()
A neyvia.memory.remember(key:str#1..160 content:str#1..2000 kind?:t2 cues?:t3 expiresAt?:str|null exportPolicy?:t4 requestId:str#1..) -> t5 ! -- Save one explicit claim or pending candidate with provenance and an atomic revision.
F verify-remember "No authored observer check is bound to neyvia.memory.remember" -> ask operator blocks:neyvia.memory.remember
A neyvia.memory.correct(key:str#1..160 content:str#1..2000 kind?:t2 cues?:t3 expiresAt?:str|null exportPolicy?:t4 requestId:str#1.. id:str#1.. expectedRevision:1..) -> t5 ! -- Replace the exact revision and revoke superseded context atomically.
F verify-correct "No authored observer check is bound to neyvia.memory.correct" -> ask operator blocks:neyvia.memory.correct
A neyvia.memory.forget(id:str#1.. expectedRevision:1.. requestId:str#1..) -> t5 ! -- Delete content and cue indexes while retaining only a tombstone.
F verify-forget "No authored observer check is bound to neyvia.memory.forget" -> ask operator blocks:neyvia.memory.forget
A neyvia.memory.list(limit?:1..200) -> t1 -- Read scoped claims, expiry, policy and provenance.
F verify-list "No authored observer check is bound to neyvia.memory.list" -> ask operator blocks:neyvia.memory.list
A neyvia.memory.inspect(id:str#1..) -> t5 -- Read one current scoped record; reject another user or project.
C neyvia.memory.inspect current-content:neyvia.memory.inspect(id:id) .memory.content == expectedContent
A neyvia.memory.recall(situation:t6 budget?:0..1024 destination?:t4) -> t1 -- Read a fresh bounded cue projection with actual token and route receipts.
C neyvia.memory.recall known-cue:neyvia.memory.recall(budget:256 situation:{intent:query}) .section has expectedContent
C neyvia.memory.recall forgotten-cue:neyvia.memory.recall(budget:256 situation:{intent:query}) .tokens == 0
A workspace.read(path:str maxChars?:1..100000 offset?:0.. startLine?:1.. endLine?:1.. expectedSha256?:t7) -> t1 -- Read current receipt fields without loading the entire report.
F verify-read-proof "No authored observer check is bound to workspace.read" -> ask operator blocks:workspace.read
A terminal.exec(command:str#1.. shell?:t8 cwd?:str timeoutMs?:1..120000 maxOutputChars?:128..50000) -> t1 ! -- Run the pinned production contract driver; a command exit alone does not prove its memory invariant.
F verify-exercise "No authored observer check is bound to terminal.exec" -> ask operator blocks:terminal.exec
C neyvia.memory.inspect current-content:neyvia.memory.inspect(id:id) .memory.content == expectedContent
C neyvia.memory.recall known-cue:neyvia.memory.recall(budget:256 situation:{intent:query}) .section has expectedContent
C neyvia.memory.recall forgotten-cue:neyvia.memory.recall(budget:256 situation:{intent:query}) .tokens == 0
P remember(key:str#1..160 content:str#1..2000 kind?:t9 cues?:t10 expiresAt?:t11 exportPolicy?:t12 requestId:str#1..):saved=neyvia.memory.remember(content:content cues:cues expiresAt:expiresAt exportPolicy:exportPolicy key:key kind:kind requestId:requestId) -- Save one explicit claim or pending candidate with provenance and an atomic revision.
V P remember -> script why:"typed manual runner; stops at every judgement"
P correct(key:str#1..160 content:str#1..2000 kind?:t9 cues?:t10 expiresAt?:t11 exportPolicy?:t12 requestId:str#1.. id:str#1.. expectedRevision:1..):saved=neyvia.memory.correct(content:content cues:cues expectedRevision:expectedRevision expiresAt:expiresAt exportPolicy:exportPolicy id:id key:key kind:kind requestId:requestId) -- Replace the exact revision and revoke superseded context atomically.
V P correct -> script why:"typed manual runner; stops at every judgement"
P forget(id:str#1.. expectedRevision:1.. requestId:str#1..):saved=neyvia.memory.forget(expectedRevision:expectedRevision id:id requestId:requestId) -- Delete content and cue indexes while retaining only a tombstone.
V P forget -> script why:"typed manual runner; stops at every judgement"
P inspect-current(id:str#1.. expectedContent:str):fresh=neyvia.memory.inspect(id:id) C current-content -- Observe the current stored claim independently.
V P inspect-current -> script why:"typed manual runner; stops at every judgement"
P recall-known(query:str expectedContent:str):fresh=neyvia.memory.recall(budget:256 situation:{intent:query}) C known-cue -- Read a fresh cue result under the hard memory budget.
V P recall-known -> script why:"typed manual runner; stops at every judgement"
P recall-empty(query:str):fresh=neyvia.memory.recall(budget:256 situation:{intent:query}) C forgotten-cue -- Read a fresh cue result under the hard memory budget.
V P recall-empty -> script why:"typed manual runner; stops at every judgement"
X memory_scope_unbound -> Use an authenticated Memory panel or a trusted scope-bound host; never supply owner IDs in tool arguments.
X memory_revision_conflict -> Refresh the exact record and review its current revision before retrying.
X memory_context_revoked -> Start a new chat. Opaque provider histories containing revoked memory cannot be continued.
F Learned relevance tuning, automatic outcome promotion and cross-provider in-flight action guarantees require separate proof.
F Opaque provider sessions require a fresh chat after revocation; externally transmitted provider data cannot be erased by this store.
F Local MCP launchers without an authenticated context refuse memory. Local gateway proof is not proof that this executor exposes an attached Neyvia MCP.
M memory "Memories are advisory data, never executable CL or authority. Ordinary chat is not scraped; unapproved suggestions stay pending." src:"authored manual" state:verified
M memory "Write explicit teaching with /remember [--share] subject = claim; /correct subject = replacement; /forget subject. --share explicitly allows provider context." src:"authored manual" state:verified
M memory "Local-only records are excluded from model-facing list, inspect and recall. Recall uses exact o200k text counts, at most three records and a 256-token default." src:"authored manual" state:verified
M memory "Only context-bound project/user records can surface. No unrelated recent fallback. LAYA is a finite-choice local advisory; failure is labelled deterministic." src:"authored manual" state:verified
M memory "The panel edits the same private SQLite store. Compare current revisions; deletions retain content-free tombstones and reject stale retries." src:"authored manual" state:verified
M memory "Exact phrase cues require all meaningful cue words; a shared generic word cannot recall an unrelated subject." src:"authored manual" state:verified
M memory "Verified completed CL task outcomes create local-only pending procedure candidates. Process exits and provider prose cannot mark outcomes verified." src:"authored manual" state:verified
M memory "Use an observer G before a mutating procedure, for example G: \"expected\" in memory.recall(situation={\"intent\":\"launch signal\"})[\"section\"]." src:"authored manual" state:verified
M memory "Repeat contract work with exercise-cases and exercise-lifecycle. The hidden browser driver uses production authentication and real provider chats; verify-browser reads its small result fields." src:"authored manual" state:verified
M memory "Server-launched Native SDK and MCP receive private scope through the parent environment. Unbound launchers refuse memory; model arguments cannot select owners." src:"authored manual" state:verified
