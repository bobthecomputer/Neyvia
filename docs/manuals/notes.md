<!-- Generated from manuals/cl/notes.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# notes

## overview
CL 1
L notes v1 -- Markdown notes folder: list, search, tags, pins, safe writes
T t1{folder:str exists:bool notes:json:"{\"type\":\"array\"}" tags:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3{modified:str body:str ..}
T t4 json:"{\"type\":\"string\",\"enum\":[\"replace\",\"append\"]}"
S notes.current:t1=neyvia.notes.list()
A neyvia.notes.list(query?:str tag?:str limit?:1..500) -> t1 -- Read up to 3000 eligible notes, pinned then recent; return filtered notes and tag counts
F verify-notes-list "No authored observer check is bound to neyvia.notes.list" -> ask operator blocks:neyvia.notes.list
A neyvia.notes.folder(folder?:str) -> t2 ! -- Persist selected folder and create it if needed; existing notes are not moved
F verify-notes-folder "No authored observer check is bound to neyvia.notes.folder" -> ask operator blocks:neyvia.notes.folder
A neyvia.notes.open(path:str) -> t2 ! -- Emit notes.open to user app; receipt alone has uiVerified=false
F verify-notes-open "No authored observer check is bound to neyvia.notes.open" -> ask operator blocks:neyvia.notes.open
A neyvia.notes.pin(path:str pinned?:bool) -> t2 ! -- Atomically update .neyvia-notes.json pin list; note bytes unchanged
C neyvia.notes.pin pin-saved:neyvia.notes.read(path:path) .pinned == true
A neyvia.notes.read(path:str) -> t3 -- Return body, relative path, tags, pinned and nanosecond modified stamp
C neyvia.notes.read tagged:neyvia.notes.read(path:path) .tags has tag
A neyvia.notes.search(query:str limit?:1..500) -> t2 -- Read matching note snippets ranked by title match then recency; no model call
F verify-notes-search "No authored observer check is bound to neyvia.notes.search" -> ask operator blocks:neyvia.notes.search
A neyvia.notes.write(path?:str title?:str body:str mode?:t4 expectedModified?:str) -> t2 ! -- Atomically create or replace Markdown; append adds newline-separated text; no path chooses a unique title filename
C neyvia.notes.write captured:neyvia.notes.read(path:path) .body has idea
C neyvia.notes.write body-saved:neyvia.notes.read(path:path) .body == body
C neyvia.notes.read captured:neyvia.notes.read(path:path) .body has idea
C neyvia.notes.read tagged:neyvia.notes.read(path:path) .tags has tag
C neyvia.notes.read body-saved:neyvia.notes.read(path:path) .body == body
C neyvia.notes.read pin-saved:neyvia.notes.read(path:path) .pinned == true
P capture-tagged-idea(path:str idea:str tag:str):before=neyvia.notes.read(path:path); J capture=append; written=neyvia.notes.write(body:idea expectedModified:before.modified mode:"append" path:path) C captured; after=neyvia.notes.read(path:path) C tagged -- Read a note, choose append, save the dictated idea with its prose tag and verify both
V P capture-tagged-idea -> script why:"typed manual runner; stops at every judgement"
P write-and-pin(path:str body:str expectedModified:str):current=neyvia.notes.read(path:path); J replace-note=replace; written=neyvia.notes.write(body:body expectedModified:expectedModified path:path) C body-saved; pinned=neyvia.notes.pin(path:path pinned:true) C pin-saved -- Review replacement of an existing note, CAS-write the body and pin it
V P write-and-pin -> script why:"typed manual runner; stops at every judgement"
P verify-effect-notes-pin(path:str):effect=neyvia.notes.pin(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-pin -> script why:"typed manual runner; stops at every judgement"
P verify-effect-notes-write(body:str):effect=neyvia.notes.write(body:body) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-write -> script why:"typed manual runner; stops at every judgement"
P verify-effect-notes-folder(folder:str):effect=neyvia.notes.folder(folder:folder) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-folder -> script why:"typed manual runner; stops at every judgement"
J capture append|leave:"Add this dictated idea to the selected note or keep the note unchanged?" -- Input idea is already transcribed and includes a prose #tag; confirm destination/topic before append. Re-read after conflicts; no automatic replacement of concurrent text.
V J capture -> human:operator why:"explicit choice required"
J replace-note replace|leave:"Does the proposed body preserve what matters in this existing note?" -- Compare current body before replacing; expectedModified comes from that observation. There is no automatic undo for note bytes.
V J replace-note -> human:operator why:"explicit choice required"
X status=conflict from expectedModified -> Read new modified/body and merge the idea; do not retry stale stamp or remove guard
X Tag absent from tags[] -> Put #tag in prose outside backticks/fences; numeric/hex-looking tags and link anchors do not count
X Changing notes.folder appears to lose notes -> Folder selection does not move files; switch back or explicitly migrate chosen files
X A note is absent from list -> Check extension, hidden/_ directories, 2 MiB limit and 3000-file scan bound; read known path directly
F Mic recording, language routing and transcription quality are outside notes.write; use dictation manual when present
F No version history, note-delete or multi-writer merge tool; preserve body before replacement
M notes "Source: src/grant_agent/neyvia_notes_tools.py (_note_path, write_note, tags_of, _all); tests/test_neyvia_notes_files.py." src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.before","proofs_notes_files.self_check"],"claim":"Every explicit note path resolves under the selected notes folder with .md, .markdown or .txt extension.","id":"notes.path-jail","impact":["notes bytes","Notes UI","note tools"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_notes_tools.tags_of/title_of -> proofs_notes_files.check_tags/check_title","proofs_notes_files.self_check"],"claim":"Tags are unique ordered case-folded prose tags excluding code, anchors and digit-containing hex colours; title uses first-six-line heading or filename stem.","id":"notes.prose-metadata","impact":["Notes list/read/write/search summaries"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.after","proofs_notes_files.self_check"],"claim":"Creation, replacement and append persist the exact requested UTF-8 body and return its filesystem modification stamp.","id":"notes.body-durable","impact":["Notes bytes","Notes editor","downstream readers"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"A stale expectedModified write returns conflict and preserves the original bytes.","id":"notes.stale-preserves","impact":["Concurrent note writers","Notes editor"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.after","proofs_notes_files.self_check"],"claim":"Pin result equals the requested state and persisted .neyvia-notes.json membership.","id":"notes.pin-durable","impact":["Notes ordering","metadata"],"phase":"post"}
