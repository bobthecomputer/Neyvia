<!-- Generated from manuals/cl/handoff-recovery.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# handoff-recovery

## intake
CL 1
L handoff-recovery v1 -- Reviewed handoff intake: Notes + Files, not a generic model benchmark
T t1{folder:str exists:bool notes:json:"{\"type\":\"array\"}" tags:json:"{\"type\":\"array\"}" ..}
T t2{body:str modified:str pinned:bool ..}
T t3 json:"{\"type\":\"string\",\"enum\":[\"replace\",\"append\"]}"
T t4 json:"{\"type\":\"object\"}"
S handoff-recovery.note:t1=neyvia.notes.list()
A neyvia.notes.read(path:str) -> t2 -- Return body, relative path, tags, pinned and nanosecond modified stamp
F verify-notes-read "No authored observer check is bound to neyvia.notes.read" -> ask operator blocks:neyvia.notes.read
A neyvia.notes.write(path?:str title?:str body:str mode?:t3 expectedModified?:str) -> t4 ! -- Atomically create or replace Markdown; append adds newline-separated text; no path chooses a unique title filename
C neyvia.notes.write captured:neyvia.notes.read(path:path) .body has message
A neyvia.notes.pin(path:str pinned?:bool) -> t4 ! -- Atomically update .neyvia-notes.json pin list; note bytes unchanged
C neyvia.notes.pin pinned:neyvia.notes.read(path:path) .pinned == true
A neyvia.files.stat(path:str preview?:bool) -> t4 -- Return kind/size/openWith; preview=true reads first 64 KiB only for text/notes
F verify-files-stat "No authored observer check is bound to neyvia.files.stat" -> ask operator blocks:neyvia.files.stat
A neyvia.files.move(from:str to:str) -> t4 ! -- Move/rename without overwrite; an existing destination folder receives source.name; replace undo receipt
F verify-files-move "No authored observer check is bound to neyvia.files.move" -> ask operator blocks:neyvia.files.move
C neyvia.notes.read captured:neyvia.notes.read(path:path) .body has message
C neyvia.notes.read pinned:neyvia.notes.read(path:path) .pinned == true
P stage-reviewed(path:str message:str source:str target:str):before=neyvia.notes.read(path:path); selected=neyvia.files.stat(path:source preview:true); J approval=approved; moved=neyvia.files.move(from:source to:target); written=neyvia.notes.write(body:message expectedModified:before.modified mode:"append" path:path) C captured; pin=neyvia.notes.pin(path:path pinned:true) C pinned -- Move the explicitly reviewed draft, append its #ready receipt once and pin it
V P stage-reviewed -> script why:"typed manual runner; stops at every judgement"
P record-review(path:str message:str source:str target:str):before=neyvia.notes.read(path:path); J receipt=record; written=neyvia.notes.write(body:message expectedModified:before.modified mode:"append" path:path) C captured; pin=neyvia.notes.pin(path:path pinned:true) C pinned -- Hold unreviewed draft and append/pin a #needs-review receipt
V P record-review -> script why:"typed manual runner; stops at every judgement"
P record-blocked(path:str message:str source:str target:str):before=neyvia.notes.read(path:path); J receipt=record; written=neyvia.notes.write(body:message expectedModified:before.modified mode:"append" path:path) C captured; pin=neyvia.notes.pin(path:path pinned:true) C pinned -- Preserve both colliding drafts and append/pin a #blocked receipt
V P record-blocked -> script why:"typed manual runner; stops at every judgement"
P capture-once(path:str message:str source:str target:str):before=neyvia.notes.read(path:path); J capture=record; written=neyvia.notes.write(body:message expectedModified:before.modified mode:"append" path:path) C captured; pin=neyvia.notes.pin(path:path pinned:true) C pinned -- Guarded idempotent capture with a fresh read and an explicit record/skip decision
V P capture-once -> script why:"typed manual runner; stops at every judgement"
P restore-selected(path:str message:str source:str target:str):before=neyvia.notes.read(path:path); selected=neyvia.files.stat(path:source preview:true); J restore=restore; moved=neyvia.files.move(from:source to:target); written=neyvia.notes.write(body:message expectedModified:before.modified mode:"append" path:path) C captured; pin=neyvia.notes.pin(path:path pinned:true) C pinned -- Restore the selected staged draft without undoing unrelated Files operations; append/pin #restored receipt
V P restore-selected -> script why:"typed manual runner; stops at every judgement"
J capture record|skip:"Does the exact message already occur in before.body?" -- Choose skip when already captured. Otherwise record only by guarded append. A failed conflict run is not resumable: reconcile actual note, restart fresh and choose skip if message already exists.
V J capture -> human:operator why:"explicit choice required"
J approval approved|stop:"Is the draft reviewed and its exact destination absent?" -- Only explicit reviewed approval with absent destination allows the move. Pending review uses record-review; collisions use record-blocked. Do not overwrite or invent another destination.
V J approval -> human:operator why:"explicit choice required"
J receipt record|stop:"Is this the authorized handoff receipt for the selected task?" -- Record the exact tagged message in the selected note; preserve draft bytes. Pin the receipt so Paul can find it.
V J receipt -> human:operator why:"explicit choice required"
J restore restore|stop:"Is source the selected staged draft and target its original absent path?" -- Restore by explicit files.move. Global files.undo targets the most recent operation and must not undo another operation.
V J restore -> human:operator why:"explicit choice required"
X notes.write returns ok=false status=conflict after another editor changed the note -> Do not drop expectedModified or resume the failed run. Start a fresh capture-once run, inspect before.body, then record or skip. Retain concurrent editor text.
X A destination exists -> Do not rename the destination, overwrite, undo it or choose a suffix. Keep both originals and record-blocked with #blocked.
X Another Files operation followed staging -> Use restore-selected with the staged path as source and original path as target. Never call global files.undo.
F This manual supplies environment-specific receipt conventions; passing it does not prove general model improvement.
F Judgement decisions are external inputs. Deterministic procedure token accounting excludes human/model judgement.
F A move or note receipt proves backend state, not rendered UI.
M handoff-recovery "Task mapping: approved => stage-reviewed (approval=approved); pending => record-review (receipt=record); collision => record-blocked (receipt=record); stale and duplicate => capture-once (capture=record if message absent, otherwise skip); undo => restore-selected (restore=restore)." src:"authored manual" state:verified
M handoff-recovery "Always use the exact supplied path/message/source/target inputs. Raw equivalent actions are allowed; procedure use is not required for scoring." src:"authored manual" state:verified
M handoff-recovery "Every new receipt uses guarded append and is pinned. Exact already-present receipt stays unchanged. Pending and collision tasks do not move files." src:"authored manual" state:verified
M handoff-recovery "Stale case: the fixture makes one real concurrent edit after first read/judge. A failed verifier is a stop, not success. Re-read via a fresh capture-once run and preserve both paragraphs." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.checkpoints.CheckpointStore.save -> check_checkpoint","grant_agent.proofs_a_capabilities.self_check"],"claim":"Saved checkpoints reread as the complete record with no atomic-write temporary tails.","id":"a.checkpoint-durable","impact":["bounded local capability actions","agent/operator evidence","recoverable scratch state"],"phase":"goal"}

## proofs_a_capabilities
CL 1
L handoff-recovery v1 -- Capability action contracts (PROOFS-a)
X Scratch receipt is mistaken for external runtime or rendered UI evidence -> Use a real rendered or authorized external journey before claiming those boundaries
F Unmapped original cases remain protected until complete equivalent contracts and startup receipts exist
M handoff-recovery "Behavior plans preserve selected capsule gates and bounded learned vectors; compiler cache remains observable." src:"authored manual" state:verified
M handoff-recovery "Challenge selection follows configured token relevance; checkpoint saving verifies the durable full record." src:"authored manual" state:verified
M handoff-recovery "Capability descriptions bind actual adapter state; artifact lineage binds local file hashes and persistent relation endpoints." src:"authored manual" state:verified
M handoff-recovery "Typed recovery remains review-only and does not retain narrative file bodies." src:"authored manual" state:verified
M handoff-recovery "Run neyvia verify --areas a-capabilities in isolated scratch state." src:"authored manual" state:verified
M handoff-recovery "Capability initialization uses an explicit empty vault configuration under disposable proof state. Saved broker/account configurations are never read; these procedures make no vault/account execution claim." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.checkpoints.CheckpointStore.save -> check_checkpoint","grant_agent.proofs_a_capabilities.self_check"],"claim":"Saved checkpoints reread as the complete record with no atomic-write temporary tails.","id":"a.checkpoint-durable","impact":["bounded local capability actions","agent/operator evidence","recoverable scratch state"],"phase":"goal"}
