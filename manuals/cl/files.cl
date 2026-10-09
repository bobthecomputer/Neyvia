CL 1
L files v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"File explorer places, quick look, move, Recycle Bin and undo"}},"clVersion":"1.1","id":"files","kind":"environment","proofs":{"area":"notes-files"},"schema":"neyvia.manual.v1","schemas":{"neyvia.files.list":"t1","neyvia.files.mkdir":"t2","neyvia.files.move":"t3","neyvia.files.stat":"t4","neyvia.files.trash":"t2","neyvia.files.undo":"t5"},"tool_metadata":{"neyvia.files.list":{"mutability_class":"read"},"neyvia.files.mkdir":{"mutability_class":"none"},"neyvia.files.move":{"mutability_class":"none"},"neyvia.files.stat":{"mutability_class":"read"},"neyvia.files.trash":{"mutability_class":"none"},"neyvia.files.undo":{"mutability_class":"none"}}}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before","proofs_notes_files.self_check"],"claim":"Move and move-undo refuse an occupied target without changing either item's bytes.","id":"files.no-overwrite","impact":["Files UI","file bytes","original paths"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Move and undo preserve the exact item bytes or directory tree and vacate the previous path.","id":"files.move-conservation","impact":["Filesystem paths","Notes references","Files UI"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Mkdir creates a previously absent directory.","id":"files.mkdir-durable","impact":["Filesystem directory","Files undo receipt"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"A successful action saves one undo receipt; undo restores that action and consumes the receipt, refusing a second undo.","id":"files.undo-once","impact":["Files UI and model undo state"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.parse_recycle_info -> proofs_notes_files.check_recycle_record","proofs_notes_files.self_check"],"claim":"Every decoded v1/v2 OS recycle record agrees with binary original path, size and deletion time; v2 length is bounded.","id":"files.recycle-record","impact":["Recycle Bin lookup","file restoration"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Trash removes the source and records recoverable equal bytes/tree in the Windows Recycle Bin; undo restores exact bytes/tree.","id":"files.trash-recoverable","impact":["Recycle Bin","original item","Files undo"],"phase":"post"}
T t1{path?:str showHidden?:bool ..}
T t2 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"path\"],\"allOf\":[{\"properties\":{\"path\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t3 json:"{\"type\":\"object\",\"properties\":{\"from\":{\"type\":\"string\"},\"to\":{\"type\":\"string\"}},\"required\":[\"from\",\"to\"],\"allOf\":[{\"properties\":{\"from\":{\"not\":{\"enum\":[\"\"]}},\"to\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t4 json:"{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"},\"preview\":{\"type\":\"boolean\"}},\"required\":[\"path\"],\"allOf\":[{\"properties\":{\"path\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t5{..}
T t6{}
T t7{entries:json:"{\"type\":\"array\"}" places:json:"{\"type\":\"array\"}" ..}
T t8 json:"{\"type\":\"object\",\"properties\":{\"entries\":{\"type\":\"array\"},\"path\":{\"type\":[\"string\",\"null\"]},\"places\":{\"type\":\"array\"},\"crumbs\":{\"type\":\"array\"},\"hiddenCount\":{\"type\":\"integer\"},\"truncated\":{\"type\":\"boolean\"}},\"required\":[\"entries\",\"path\"],\"anyOf\":[{\"properties\":{\"path\":{\"type\":\"null\"}},\"required\":[\"places\"]},{\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"parent\",\"place\",\"crumbs\",\"hiddenCount\",\"truncated\"]}]}"
T t9 json:"{\"type\":\"object\"}"
T t10{from:str to:str name:str}
T t11{from:str to:str originalName:str}
T t12{path:str ..}
T t13{from:str to:str ..}
L files.overview v1 -- File explorer places, quick look, move, Recycle Bin and undo
-- @record {"chapter":"overview","data":{"args":{},"inputs":{"$cl_type":"t6"},"shape":{"$cl_type":"t7"},"tool":"neyvia.files.list"},"key":"current","section":"state"}
S files.current:{entries:json:"{\"type\":\"array\"}" places:json:"{\"type\":\"array\"}" ..}=neyvia.files.list()
-- @record {"chapter":"overview","data":{"effect":"Return folders-first entries, hidden count and truncated flag at 2000 entries","pre":"No path lists existing places; supplied path resolves inside Home/workspace/notes/project places and is a directory outside protected tree","returns":{"$cl_type":"t8"},"reversible":true,"schema":"neyvia.files.list","tool":"neyvia.files.list"},"key":"files.list","section":"actions"}
A neyvia.files.list(path?:str showHidden?:bool) -> json:"{\"type\":\"object\",\"properties\":{\"entries\":{\"type\":\"array\"},\"path\":{\"type\":[\"string\",\"null\"]},\"places\":{\"type\":\"array\"},\"crumbs\":{\"type\":\"array\"},\"hiddenCount\":{\"type\":\"integer\"},\"truncated\":{\"type\":\"boolean\"}},\"required\":[\"entries\",\"path\"],\"anyOf\":[{\"properties\":{\"path\":{\"type\":\"null\"}},\"required\":[\"places\"]},{\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"parent\",\"place\",\"crumbs\",\"hiddenCount\",\"truncated\"]}]}" -- Return folders-first entries, hidden count and truncated flag at 2000 entries
F verify-files-list "No authored observer check is bound to neyvia.files.list" -> ask operator blocks:neyvia.files.list
-- @record {"chapter":"overview","data":{"effect":"Create one folder and replace the one-step Files undo receipt","pre":"Guarded absent path with an existing parent directory","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.files.mkdir","tool":"neyvia.files.mkdir"},"key":"files.mkdir","section":"actions"}
A neyvia.files.mkdir(path:str) -> json:"{\"type\":\"object\"}" ! -- Create one folder and replace the one-step Files undo receipt
F verify-files-mkdir "No authored observer check is bound to neyvia.files.mkdir" -> ask operator blocks:neyvia.files.mkdir
-- @record {"chapter":"overview","data":{"effect":"Move/rename without overwrite; an existing destination folder receives source.name; replace undo receipt","pre":"Existing guarded source; destination parent exists, destination absent except case rename; no folder into itself; model approval for both non-workspace/non-notes places","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.files.move","tool":"neyvia.files.move"},"key":"files.move","section":"actions"}
A neyvia.files.move(from:str to:str) -> json:"{\"type\":\"object\"}" ! -- Move/rename without overwrite; an existing destination folder receives source.name; replace undo receipt
C neyvia.files.move target-name:neyvia.files.stat(path:to) .name == name
-- @record {"chapter":"overview","data":{"effect":"Return kind/size/openWith; preview=true reads first 64 KiB only for text/notes","pre":"Existing guarded path inside a Files place outside protected tree","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.files.stat","tool":"neyvia.files.stat"},"key":"files.stat","section":"actions"}
A neyvia.files.stat(path:str preview?:bool) -> json:"{\"type\":\"object\"}" -- Return kind/size/openWith; preview=true reads first 64 KiB only for text/notes
F verify-files-stat "No authored observer check is bound to neyvia.files.stat" -> ask operator blocks:neyvia.files.stat
-- @record {"chapter":"overview","data":{"effect":"Recycle item, verify source disappeared and replace undo receipt; never permanent delete","pre":"Existing guarded item, not a place root, <=2 GiB; model approval for non-workspace/non-notes place; available Recycle Bin","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.files.trash","tool":"neyvia.files.trash"},"key":"files.trash","section":"actions"}
A neyvia.files.trash(path:str) -> json:"{\"type\":\"object\"}" -- Recycle item, verify source disappeared and replace undo receipt; never permanent delete
F verify-files-trash "No authored observer check is bound to neyvia.files.trash" -> ask operator blocks:neyvia.files.trash
-- @record {"chapter":"overview","data":{"effect":"Reverse the one retained Files action then clear receipt; later UI/model actions overwrite undo history","pre":"Last Files receipt exists; move target still exists and old location is vacant; mkdir still empty; trash record and original parent available on Windows","returns":{"$cl_type":"t9"},"reversible":true,"schema":"neyvia.files.undo","tool":"neyvia.files.undo"},"key":"files.undo","section":"actions"}
A neyvia.files.undo() -> json:"{\"type\":\"object\"}" -- Reverse the one retained Files action then clear receipt; later UI/model actions overwrite undo history
C neyvia.files.undo restored-name:neyvia.files.stat(path:from) .name == originalName
C neyvia.files.undo restored-name:neyvia.files.stat(path:from) .name == originalName
-- @record {"chapter":"overview","data":{"args":{"path":{"$path":"to"}},"expect":{"op":"eq","path":"name","value":{"$input":"name"}},"tool":"neyvia.files.stat"},"key":"target-name","section":"checks"}
C neyvia.files.stat target-name:neyvia.files.stat(path:to) .name == name
-- @record {"chapter":"overview","data":{"args":{"path":{"$path":"from"}},"expect":{"op":"eq","path":"name","value":{"$input":"originalName"}},"tool":"neyvia.files.stat"},"key":"restored-name","section":"checks"}
C neyvia.files.stat restored-name:neyvia.files.stat(path:from) .name == originalName
-- @record {"chapter":"overview","data":{"goal":"Inspect one item, review its destination and move without overwrite; undo-last-tidy reverses immediately","inputs":{"$cl_type":"t10"},"steps":[{"action":"files.stat","args":{"path":{"$path":"from"},"preview":true},"save":"before"},{"judge":"tidy"},{"action":"files.move","args":{"from":{"$path":"from"},"to":{"$path":"to"}},"check":"target-name","save":"moved","when":{"judge":"tidy","option":"move"}}]},"key":"tidy-with-undo","section":"procedures"}
P tidy-with-undo(from:str to:str name:str):before=neyvia.files.stat(path:from preview:true); J tidy=move; moved=neyvia.files.move(from:from to:to) C target-name -- Inspect one item, review its destination and move without overwrite; undo-last-tidy reverses immediately
V P tidy-with-undo -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Rename/move an explicitly selected item to an absent full destination and verify its name","inputs":{"$cl_type":"t10"},"steps":[{"action":"files.stat","args":{"path":{"$path":"from"}},"save":"before"},{"judge":"tidy"},{"action":"files.move","args":{"from":{"$path":"from"},"to":{"$path":"to"}},"check":"target-name","save":"moved","when":{"judge":"tidy","option":"move"}}]},"key":"rename-and-check","section":"procedures"}
P rename-and-check(from:str to:str name:str):before=neyvia.files.stat(path:from); J tidy=move; moved=neyvia.files.move(from:from to:to) C target-name -- Rename/move an explicitly selected item to an absent full destination and verify its name
V P rename-and-check -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Immediately review a successful Files move and undo it if unwanted","inputs":{"$cl_type":"t11"},"steps":[{"action":"files.stat","args":{"path":{"$path":"to"}},"save":"movedItem"},{"judge":"retain"},{"action":"files.undo","args":{},"check":"restored-name","save":"undone","when":{"judge":"retain","option":"undo"}}]},"key":"undo-last-tidy","section":"procedures"}
P undo-last-tidy(from:str to:str originalName:str):movedItem=neyvia.files.stat(path:to); J retain=undo; undone=neyvia.files.undo() C restored-name -- Immediately review a successful Files move and undo it if unwanted
V P undo-last-tidy -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t12"},"steps":[{"action":"files.mkdir","args":{"path":{"$input":"path"}},"save":"effect"}]},"key":"verify-effect-files-mkdir","section":"procedures"}
P verify-effect-files-mkdir(path:str):effect=neyvia.files.mkdir(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-mkdir -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t13"},"steps":[{"action":"files.move","args":{"from":{"$input":"from"},"to":{"$input":"to"}},"save":"effect"}]},"key":"verify-effect-files-move","section":"procedures"}
P verify-effect-files-move(from:str to:str):effect=neyvia.files.move(from:from to:to) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-move -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t12"},"steps":[{"action":"files.trash","args":{"path":{"$input":"path"}},"save":"effect"}]},"key":"verify-effect-files-trash","section":"procedures"}
P verify-effect-files-trash(path:str):effect=neyvia.files.trash(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-trash -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Move one selected item, undo that move and verify through a fresh observer that the original name is back","inputs":{"$cl_type":"t11"},"steps":[{"action":"files.move","args":{"from":{"$path":"from"},"to":{"$path":"to"}},"save":"moved"},{"action":"files.undo","args":{},"check":"restored-name","save":"effect"}]},"key":"verify-effect-files-undo","section":"procedures"}
P verify-effect-files-undo(from:str to:str originalName:str):moved=neyvia.files.move(from:from to:to); effect=neyvia.files.undo() C restored-name -- Move one selected item, undo that move and verify through a fresh observer that the original name is back
V P verify-effect-files-undo -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Choose by project/topic and preserve filename unless rename requested. Destination folder must exist; a collision stops the chain. The next Files operation replaces undo history.","options":["move","leave"],"question":"Is the proposed destination appropriate for this item?"},"key":"tidy","section":"judge"}
J tidy move|leave:"Is the proposed destination appropriate for this item?" -- Choose by project/topic and preserve filename unless rename requested. Destination folder must exist; a collision stops the chain. The next Files operation replaces undo history.
V J tidy -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"constraints":"Run only immediately after a successful move with no intervening Files UI/model mutation. Inspect the moved item first; undo refuses occupied original paths.","options":["keep","undo"],"question":"Keep this move or put the item back?"},"key":"retain","section":"judge"}
J retain keep|undo:"Keep this move or put the item back?" -- Run only immediately after a successful move with no intervening Files UI/model mutation. Inspect the moved item first; undo refuses occupied original paths.
V J retain -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"Destination already exists or folder is moved into itself","recovery":"Choose another absent destination; never trash collision to force move"},"key":"0","section":"pitfalls"}
X Destination already exists or folder is moved into itself -> Choose another absent destination; never trash collision to force move
-- @record {"chapter":"overview","data":{"failure":"Undo restores another operation","recovery":"Only one Files action is retained across UI/model; inspect last action in UI and reconcile before undo"},"key":"1","section":"pitfalls"}
X Undo restores another operation -> Only one Files action is retained across UI/model; inspect last action in UI and reconcile before undo
-- @record {"chapter":"overview","data":{"failure":"Trash drive has no Recycle Bin or item exceeds 2 GiB","recovery":"Nothing should be deleted; keep item and ask owner to use Explorer"},"key":"2","section":"pitfalls"}
X Trash drive has no Recycle Bin or item exceeds 2 GiB -> Nothing should be deleted; keep item and ask owner to use Explorer
-- @record {"chapter":"overview","data":{"failure":"Home/project move returns approval_required","recovery":"Owner must approve that place; workspace/notes exemptions do not extend to Home"},"key":"3","section":"pitfalls"}
X Home/project move returns approval_required -> Owner must approve that place; workspace/notes exemptions do not extend to Home
-- @record {"chapter":"overview","data":{"failure":"Folder listing is truncated at 2000 entries","recovery":"Browse a narrower subfolder; absence from this listing proves nothing"},"key":"4","section":"pitfalls"}
X Folder listing is truncated at 2000 entries -> Browse a narrower subfolder; absence from this listing proves nothing
-- @record {"chapter":"overview","data":"Remote paths require cross-pc manual; no remote rename/delete","key":"0","section":"frontier"}
F Remote paths require cross-pc manual; no remote rename/delete
-- @record {"chapter":"overview","data":"No batch undo journal; mkdir then move retains only the move","key":"1","section":"frontier"}
F No batch undo journal; mkdir then move retains only the move
-- @record {"chapter":"overview","data":"Source: src/grant_agent/neyvia_files_tools.py (guard, move, _approval, trash, undo); tests/test_neyvia_notes_files.py.","key":"0","section":"guidance"}
M files "Source: src/grant_agent/neyvia_files_tools.py (guard, move, _approval, trash, undo); tests/test_neyvia_notes_files.py." src:"authored manual" state:verified
