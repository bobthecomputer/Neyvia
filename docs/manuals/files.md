<!-- Generated from manuals/cl/files.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# files

## overview
CL 1
L files v1 -- File explorer places, quick look, move, Recycle Bin and undo
T t1{entries:json:"{\"type\":\"array\"}" places:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\",\"properties\":{\"entries\":{\"type\":\"array\"},\"path\":{\"type\":[\"string\",\"null\"]},\"places\":{\"type\":\"array\"},\"crumbs\":{\"type\":\"array\"},\"hiddenCount\":{\"type\":\"integer\"},\"truncated\":{\"type\":\"boolean\"}},\"required\":[\"entries\",\"path\"],\"anyOf\":[{\"properties\":{\"path\":{\"type\":\"null\"}},\"required\":[\"places\"]},{\"properties\":{\"path\":{\"type\":\"string\"}},\"required\":[\"parent\",\"place\",\"crumbs\",\"hiddenCount\",\"truncated\"]}]}"
T t3 json:"{\"type\":\"object\"}"
S files.current:t1=neyvia.files.list()
A neyvia.files.list(path?:str showHidden?:bool) -> t2 -- Return folders-first entries, hidden count and truncated flag at 2000 entries
F verify-files-list "No authored observer check is bound to neyvia.files.list" -> ask operator blocks:neyvia.files.list
A neyvia.files.mkdir(path:str) -> t3 ! -- Create one folder and replace the one-step Files undo receipt
F verify-files-mkdir "No authored observer check is bound to neyvia.files.mkdir" -> ask operator blocks:neyvia.files.mkdir
A neyvia.files.move(from:str to:str) -> t3 ! -- Move/rename without overwrite; an existing destination folder receives source.name; replace undo receipt
C neyvia.files.move target-name:neyvia.files.stat(path:to) .name == name
A neyvia.files.stat(path:str preview?:bool) -> t3 -- Return kind/size/openWith; preview=true reads first 64 KiB only for text/notes
F verify-files-stat "No authored observer check is bound to neyvia.files.stat" -> ask operator blocks:neyvia.files.stat
A neyvia.files.trash(path:str) -> t3 -- Recycle item, verify source disappeared and replace undo receipt; never permanent delete
F verify-files-trash "No authored observer check is bound to neyvia.files.trash" -> ask operator blocks:neyvia.files.trash
A neyvia.files.undo() -> t3 -- Reverse the one retained Files action then clear receipt; later UI/model actions overwrite undo history
C neyvia.files.undo restored-name:neyvia.files.stat(path:from) .name == originalName
C neyvia.files.undo restored-name:neyvia.files.stat(path:from) .name == originalName
C neyvia.files.stat target-name:neyvia.files.stat(path:to) .name == name
C neyvia.files.stat restored-name:neyvia.files.stat(path:from) .name == originalName
P tidy-with-undo(from:str to:str name:str):before=neyvia.files.stat(path:from preview:true); J tidy=move; moved=neyvia.files.move(from:from to:to) C target-name -- Inspect one item, review its destination and move without overwrite; undo-last-tidy reverses immediately
V P tidy-with-undo -> script why:"typed manual runner; stops at every judgement"
P rename-and-check(from:str to:str name:str):before=neyvia.files.stat(path:from); J tidy=move; moved=neyvia.files.move(from:from to:to) C target-name -- Rename/move an explicitly selected item to an absent full destination and verify its name
V P rename-and-check -> script why:"typed manual runner; stops at every judgement"
P undo-last-tidy(from:str to:str originalName:str):movedItem=neyvia.files.stat(path:to); J retain=undo; undone=neyvia.files.undo() C restored-name -- Immediately review a successful Files move and undo it if unwanted
V P undo-last-tidy -> script why:"typed manual runner; stops at every judgement"
P verify-effect-files-mkdir(path:str):effect=neyvia.files.mkdir(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-mkdir -> script why:"typed manual runner; stops at every judgement"
P verify-effect-files-move(from:str to:str):effect=neyvia.files.move(from:from to:to) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-move -> script why:"typed manual runner; stops at every judgement"
P verify-effect-files-trash(path:str):effect=neyvia.files.trash(path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-files-trash -> script why:"typed manual runner; stops at every judgement"
P verify-effect-files-undo(from:str to:str originalName:str):moved=neyvia.files.move(from:from to:to); effect=neyvia.files.undo() C restored-name -- Move one selected item, undo that move and verify through a fresh observer that the original name is back
V P verify-effect-files-undo -> script why:"typed manual runner; stops at every judgement"
J tidy move|leave:"Is the proposed destination appropriate for this item?" -- Choose by project/topic and preserve filename unless rename requested. Destination folder must exist; a collision stops the chain. The next Files operation replaces undo history.
V J tidy -> human:operator why:"explicit choice required"
J retain keep|undo:"Keep this move or put the item back?" -- Run only immediately after a successful move with no intervening Files UI/model mutation. Inspect the moved item first; undo refuses occupied original paths.
V J retain -> human:operator why:"explicit choice required"
X Destination already exists or folder is moved into itself -> Choose another absent destination; never trash collision to force move
X Undo restores another operation -> Only one Files action is retained across UI/model; inspect last action in UI and reconcile before undo
X Trash drive has no Recycle Bin or item exceeds 2 GiB -> Nothing should be deleted; keep item and ask owner to use Explorer
X Home/project move returns approval_required -> Owner must approve that place; workspace/notes exemptions do not extend to Home
X Folder listing is truncated at 2000 entries -> Browse a narrower subfolder; absence from this listing proves nothing
F Remote paths require cross-pc manual; no remote rename/delete
F No batch undo journal; mkdir then move retains only the move
M files "Source: src/grant_agent/neyvia_files_tools.py (guard, move, _approval, trash, undo); tests/test_neyvia_notes_files.py." src:"authored manual" state:verified
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before","proofs_notes_files.self_check"],"claim":"Move and move-undo refuse an occupied target without changing either item's bytes.","id":"files.no-overwrite","impact":["Files UI","file bytes","original paths"],"phase":"pre"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Move and undo preserve the exact item bytes or directory tree and vacate the previous path.","id":"files.move-conservation","impact":["Filesystem paths","Notes references","Files UI"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Mkdir creates a previously absent directory.","id":"files.mkdir-durable","impact":["Filesystem directory","Files undo receipt"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"A successful action saves one undo receipt; undo restores that action and consumes the receipt, refusing a second undo.","id":"files.undo-once","impact":["Files UI and model undo state"],"phase":"post"}
-- @proof {"checkedAt":["neyvia_files_tools.parse_recycle_info -> proofs_notes_files.check_recycle_record","proofs_notes_files.self_check"],"claim":"Every decoded v1/v2 OS recycle record agrees with binary original path, size and deletion time; v2 length is bounded.","id":"files.recycle-record","impact":["Recycle Bin lookup","file restoration"],"phase":"invariant"}
-- @proof {"checkedAt":["neyvia_files_tools.call_files -> proofs_notes_files.before/after","proofs_notes_files.self_check"],"claim":"Trash removes the source and records recoverable equal bytes/tree in the Windows Recycle Bin; undo restores exact bytes/tree.","id":"files.trash-recoverable","impact":["Recycle Bin","original item","Files undo"],"phase":"post"}
