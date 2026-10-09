CL 1
L notes v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Markdown notes folder: list, search, tags, pins, safe writes"}},"clVersion":"1.1","id":"notes","kind":"environment","proofs":{"area":"notes-files"},"schema":"neyvia.manual.v1","schemas":{"neyvia.notes.folder":"t1","neyvia.notes.list":"t2","neyvia.notes.open":"t3","neyvia.notes.pin":"t4","neyvia.notes.read":"t3","neyvia.notes.search":"t5","neyvia.notes.write":"t6"},"tool_metadata":{"neyvia.notes.folder":{"mutability_class":"none"},"neyvia.notes.list":{"mutability_class":"read"},"neyvia.notes.open":{"mutability_class":"none"},"neyvia.notes.pin":{"mutability_class":"none"},"neyvia.notes.read":{"mutability_class":"read"},"neyvia.notes.search":{"mutability_class":"read"},"neyvia.notes.write":{"mutability_class":"none"}}}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.before","proofs_notes_files.self_check"],"claim":"Every explicit note path resolves under the selected notes folder with .md, .markdown or .txt extension.","id":"notes.path-jail","impact":["notes bytes","Notes UI","note tools"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_notes_tools.tags_of/title_of -> proofs_notes_files.check_tags/check_title","proofs_notes_files.self_check"],"claim":"Tags are unique ordered case-folded prose tags excluding code, anchors and digit-containing hex colours; title uses first-six-line heading or filename stem.","id":"notes.prose-metadata","impact":["Notes list/read/write/search summaries"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.after","proofs_notes_files.self_check"],"claim":"Creation, replacement and append persist the exact requested UTF-8 body and return its filesystem modification stamp.","id":"notes.body-durable","impact":["Notes bytes","Notes editor","downstream readers"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"A stale expectedModified write returns conflict and preserves the original bytes.","id":"notes.stale-preserves","impact":["Concurrent note writers","Notes editor"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_notes_tools.call_notes -> proofs_notes_files.after","proofs_notes_files.self_check"],"claim":"Pin result equals the requested state and persisted .neyvia-notes.json membership.","id":"notes.pin-durable","impact":["Notes ordering","metadata"],"phase":"post"}
T t1{folder?:str ..}
T t2{query?:str tag?:str limit?:1..500 ..}
T t3 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"path\"],\"allOf\":[{\"properties\":{\"path\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t4 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"},\"pinned\":{\"type\":\"boolean\"}},\"required\":[\"path\"],\"allOf\":[{\"properties\":{\"path\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t5 json:"{\"type\":\"object\",\"properties\":{\"query\":{\"type\":\"string\"},\"limit\":{\"type\":\"integer\",\"minimum\":1,\"maximum\":500}},\"required\":[\"query\"],\"allOf\":[{\"properties\":{\"query\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t6 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"},\"title\":{\"type\":\"string\"},\"body\":{\"type\":\"string\"},\"mode\":{\"type\":\"string\",\"enum\":[\"replace\",\"append\"]},\"expectedModified\":{\"type\":\"string\"}},\"required\":[\"body\"],\"allOf\":[{\"properties\":{\"body\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t7{}
T t8{folder:str exists:bool notes:json:"{\"type\":\"array\"}" tags:json:"{\"type\":\"array\"}" ..}
T t9 json:"{\"type\":\"object\"}"
T t10{modified:str body:str ..}
T t11{path:str idea:str tag:str}
T t12{path:str body:str expectedModified:str}
T t13{path:str ..}
T t14{body:str ..}
T t15{folder:str ..}
L notes.overview v1 -- Markdown notes folder: list, search, tags, pins, safe writes
-- @record {"chapter":"overview","data":{"args":{},"inputs":{"$cl_type":"t7"},"shape":{"$cl_type":"t8"},"tool":"neyvia.notes.list"},"key":"current","section":"state"}
S notes.current:{folder:str exists:bool notes:json:"{\"type\":\"array\"}" tags:json:"{\"type\":\"array\"}" ..}=neyvia.notes.list()
-- @record {"chapter":"overview","data":{"effect":"Read up to 3000 eligible notes, pinned then recent; return filtered notes and tag counts","pre":"Configured notes folder; query words and tags are conjunctive; limit 1–500","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.notes.list","tool":"neyvia.notes.list"},"key":"notes.list","section":"actions"}
A neyvia.notes.list(query?:str tag?:str limit?:1..500) -> {folder:str exists:bool notes:json:"{\"type\":\"array\"}" tags:json:"{\"type\":\"array\"}" ..} -- Read up to 3000 eligible notes, pinned then recent; return filtered notes and tag counts
F verify-notes-list "No authored observer check is bound to neyvia.notes.list" -> ask operator blocks:neyvia.notes.list
-- @record {"chapter":"overview","data":{"effect":"Persist selected folder and create it if needed; existing notes are not moved","pre":"No folder reads current choice; supplied folder resolves outside protected live tree and is a directory or missing","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notes.folder","tool":"neyvia.notes.folder"},"key":"notes.folder","section":"actions"}
A neyvia.notes.folder(folder?:str) -> json:"{\"type\":\"object\"}" ! -- Persist selected folder and create it if needed; existing notes are not moved
F verify-notes-folder "No authored observer check is bound to neyvia.notes.folder" -> ask operator blocks:neyvia.notes.folder
-- @record {"chapter":"overview","data":{"effect":"Emit notes.open to user app; receipt alone has uiVerified=false","pre":"Existing readable note beneath configured notes folder","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notes.open","tool":"neyvia.notes.open"},"key":"notes.open","section":"actions"}
A neyvia.notes.open(path:str) -> json:"{\"type\":\"object\"}" ! -- Emit notes.open to user app; receipt alone has uiVerified=false
F verify-notes-open "No authored observer check is bound to neyvia.notes.open" -> ask operator blocks:neyvia.notes.open
-- @record {"chapter":"overview","data":{"effect":"Atomically update .neyvia-notes.json pin list; note bytes unchanged","pre":"Existing note beneath notes folder; pinned defaults true","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notes.pin","tool":"neyvia.notes.pin"},"key":"notes.pin","section":"actions"}
A neyvia.notes.pin(path:str pinned?:bool) -> json:"{\"type\":\"object\"}" ! -- Atomically update .neyvia-notes.json pin list; note bytes unchanged
C neyvia.notes.pin pin-saved:neyvia.notes.read(path:path) .pinned == true
-- @record {"chapter":"overview","data":{"effect":"Return body, relative path, tags, pinned and nanosecond modified stamp","pre":"Existing .md/.markdown/.txt resolved beneath notes folder, at most 2 MiB","returns":{"$cl_type":"t10"},"reversible":true,"schema":"neyvia.notes.read","tool":"neyvia.notes.read"},"key":"notes.read","section":"actions"}
A neyvia.notes.read(path:str) -> {modified:str body:str ..} -- Return body, relative path, tags, pinned and nanosecond modified stamp
C neyvia.notes.read tagged:neyvia.notes.read(path:path) .tags has tag
-- @record {"chapter":"overview","data":{"effect":"Read matching note snippets ranked by title match then recency; no model call","pre":"Nonblank query; every word and #tag must match; limit 1–500","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.notes.search","tool":"neyvia.notes.search"},"key":"notes.search","section":"actions"}
A neyvia.notes.search(query:str limit?:1..500) -> json:"{\"type\":\"object\"}" -- Read matching note snippets ranked by title match then recency; no model call
F verify-notes-search "No authored observer check is bound to neyvia.notes.search" -> ask operator blocks:neyvia.notes.search
-- @record {"chapter":"overview","data":{"effect":"Atomically create or replace Markdown; append adds newline-separated text; no path chooses a unique title filename","pre":"UTF-8 body <=2 MiB; explicit path stays beneath notes folder with note extension; supplied expectedModified must match an existing note","returns":{"$cl_type":"t9"},"reversible":false,"schema":"neyvia.notes.write","tool":"neyvia.notes.write"},"key":"notes.write","section":"actions"}
A neyvia.notes.write(path?:str title?:str body:str mode?:json:"{\"type\":\"string\",\"enum\":[\"replace\",\"append\"]}" expectedModified?:str) -> json:"{\"type\":\"object\"}" ! -- Atomically create or replace Markdown; append adds newline-separated text; no path chooses a unique title filename
C neyvia.notes.write captured:neyvia.notes.read(path:path) .body has idea
C neyvia.notes.write body-saved:neyvia.notes.read(path:path) .body == body
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"expect":{"op":"contains","path":"body","value":{"$input":"idea"}},"tool":"neyvia.notes.read"},"key":"captured","section":"checks"}
C neyvia.notes.read captured:neyvia.notes.read(path:path) .body has idea
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"expect":{"op":"contains","path":"tags","value":{"$input":"tag"}},"tool":"neyvia.notes.read"},"key":"tagged","section":"checks"}
C neyvia.notes.read tagged:neyvia.notes.read(path:path) .tags has tag
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"expect":{"op":"eq","path":"body","value":{"$input":"body"}},"tool":"neyvia.notes.read"},"key":"body-saved","section":"checks"}
C neyvia.notes.read body-saved:neyvia.notes.read(path:path) .body == body
-- @record {"chapter":"overview","data":{"args":{"path":{"$input":"path"}},"expect":{"op":"eq","path":"pinned","value":true},"tool":"neyvia.notes.read"},"key":"pin-saved","section":"checks"}
C neyvia.notes.read pin-saved:neyvia.notes.read(path:path) .pinned == true
-- @record {"chapter":"overview","data":{"goal":"Read a note, choose append, save the dictated idea with its prose tag and verify both","inputs":{"$cl_type":"t11"},"steps":[{"action":"notes.read","args":{"path":{"$input":"path"}},"save":"before"},{"judge":"capture"},{"action":"notes.write","args":{"body":{"$input":"idea"},"expectedModified":{"$result":"before.modified"},"mode":"append","path":{"$input":"path"}},"check":"captured","save":"written","when":{"judge":"capture","option":"append"}},{"action":"notes.read","args":{"path":{"$input":"path"}},"check":"tagged","save":"after","when":{"judge":"capture","option":"append"}}]},"key":"capture-tagged-idea","section":"procedures"}
P capture-tagged-idea(path:str idea:str tag:str):before=neyvia.notes.read(path:path); J capture=append; written=neyvia.notes.write(body:idea expectedModified:before.modified mode:"append" path:path) C captured; after=neyvia.notes.read(path:path) C tagged -- Read a note, choose append, save the dictated idea with its prose tag and verify both
V P capture-tagged-idea -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Review replacement of an existing note, CAS-write the body and pin it","inputs":{"$cl_type":"t12"},"steps":[{"action":"notes.read","args":{"path":{"$input":"path"}},"save":"current"},{"judge":"replace-note"},{"action":"notes.write","args":{"body":{"$input":"body"},"expectedModified":{"$input":"expectedModified"},"path":{"$input":"path"}},"check":"body-saved","save":"written","when":{"judge":"replace-note","option":"replace"}},{"action":"notes.pin","args":{"path":{"$input":"path"},"pinned":true},"check":"pin-saved","save":"pinned","when":{"judge":"replace-note","option":"replace"}}]},"key":"write-and-pin","section":"procedures"}
P write-and-pin(path:str body:str expectedModified:str):current=neyvia.notes.read(path:path); J replace-note=replace; written=neyvia.notes.write(body:body expectedModified:expectedModified path:path) C body-saved; pinned=neyvia.notes.pin(path:path pinned:true) C pin-saved -- Review replacement of an existing note, CAS-write the body and pin it
V P write-and-pin -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t13"},"steps":[{"action":"notes.pin","args":{"path":{"$input":"path"}},"save":"effect"}]},"key":"verify-effect-notes-pin","section":"procedures"}
P verify-effect-notes-pin(path:str):effect=neyvia.notes.pin(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-pin -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t14"},"steps":[{"action":"notes.write","args":{"body":{"$input":"body"}},"save":"effect"}]},"key":"verify-effect-notes-write","section":"procedures"}
P verify-effect-notes-write(body:str):effect=neyvia.notes.write(body:body) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-write -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t15"},"steps":[{"action":"notes.folder","args":{"folder":{"$input":"folder"}},"save":"effect"}]},"key":"verify-effect-notes-folder","section":"procedures"}
P verify-effect-notes-folder(folder:str):effect=neyvia.notes.folder(folder:folder) -- Verify the actual effect through fresh owning observers
V P verify-effect-notes-folder -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Input idea is already transcribed and includes a prose #tag; confirm destination/topic before append. Re-read after conflicts; no automatic replacement of concurrent text.","options":["append","leave"],"question":"Add this dictated idea to the selected note or keep the note unchanged?"},"key":"capture","section":"judge"}
J capture append|leave:"Add this dictated idea to the selected note or keep the note unchanged?" -- Input idea is already transcribed and includes a prose #tag; confirm destination/topic before append. Re-read after conflicts; no automatic replacement of concurrent text.
V J capture -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"constraints":"Compare current body before replacing; expectedModified comes from that observation. There is no automatic undo for note bytes.","options":["replace","leave"],"question":"Does the proposed body preserve what matters in this existing note?"},"key":"replace-note","section":"judge"}
J replace-note replace|leave:"Does the proposed body preserve what matters in this existing note?" -- Compare current body before replacing; expectedModified comes from that observation. There is no automatic undo for note bytes.
V J replace-note -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"status=conflict from expectedModified","recovery":"Read new modified/body and merge the idea; do not retry stale stamp or remove guard"},"key":"0","section":"pitfalls"}
X status=conflict from expectedModified -> Read new modified/body and merge the idea; do not retry stale stamp or remove guard
-- @record {"chapter":"overview","data":{"failure":"Tag absent from tags[]","recovery":"Put #tag in prose outside backticks/fences; numeric/hex-looking tags and link anchors do not count"},"key":"1","section":"pitfalls"}
X Tag absent from tags[] -> Put #tag in prose outside backticks/fences; numeric/hex-looking tags and link anchors do not count
-- @record {"chapter":"overview","data":{"failure":"Changing notes.folder appears to lose notes","recovery":"Folder selection does not move files; switch back or explicitly migrate chosen files"},"key":"2","section":"pitfalls"}
X Changing notes.folder appears to lose notes -> Folder selection does not move files; switch back or explicitly migrate chosen files
-- @record {"chapter":"overview","data":{"failure":"A note is absent from list","recovery":"Check extension, hidden/_ directories, 2 MiB limit and 3000-file scan bound; read known path directly"},"key":"3","section":"pitfalls"}
X A note is absent from list -> Check extension, hidden/_ directories, 2 MiB limit and 3000-file scan bound; read known path directly
-- @record {"chapter":"overview","data":"Mic recording, language routing and transcription quality are outside notes.write; use dictation manual when present","key":"0","section":"frontier"}
F Mic recording, language routing and transcription quality are outside notes.write; use dictation manual when present
-- @record {"chapter":"overview","data":"No version history, note-delete or multi-writer merge tool; preserve body before replacement","key":"1","section":"frontier"}
F No version history, note-delete or multi-writer merge tool; preserve body before replacement
-- @record {"chapter":"overview","data":"Source: src/grant_agent/neyvia_notes_tools.py (_note_path, write_note, tags_of, _all); tests/test_neyvia_notes_files.py.","key":"0","section":"guidance"}
M notes "Source: src/grant_agent/neyvia_notes_tools.py (_note_path, write_note, tags_of, _all); tests/test_neyvia_notes_files.py." src:"authored manual" state:verified
