CL 1
-- Notes layer, compiled by hand from manuals/notes.manual.json and src/grant_agent/neyvia_notes_tools.py.
-- The runtime block is a real run of that code (list, then an append with a CAS stamp) in a scratch folder,
-- shown under the default folder name. Today's format for the same content: today/notes.*

-- L0
L notes v1 tools:neyvia.notes -- Markdown notes folder: list, search, #tags, pins, CAS writes

-- L1
T tag word#1..49 -- a #word in prose; not in code, not numeric/hex, not a link anchor
T note{path:path title:str tags:[tag] modified:id excerpt:str pinned:bool ^changed:time ^size:int ^file:path}
T notes{folder:path exists:bool total:int items:[note] tags:[{tag:tag count:int}]}
S notes:notes = notes.list()
A notes.list(query?:str tag?:tag limit?:1..500) -> notes -- pinned first, then newest; every word and #tag must match
I notes.list reads:folder bounds:"3000 files, 2MiB each"
A notes.search(query:str#1.. limit?:1..500) -> notes -- title hits first, then recency; snippets
I notes.search reads:folder
A notes.read(path:path) -> note{body:str}
I notes.read reads:folder/path
A notes.write(body:str path?:path title?:str mode?:replace|append expectedModified?:id) -> note ! -- no path: new unique file named from title
I notes.write writes:folder/path emits:notes.changed ui:Notes deps:[tags,pins,open-editors] undo:none ask:none -- CAS: pass expectedModified from your last read
C notes.write pre: bytes(body)<=2MiB
C notes.write cas: result.status!="conflict"
C notes.write saved: notes.read(result.path).body has body
A notes.pin(path:path pinned?:bool=true) -> {path:path pinned:bool} ~
I notes.pin writes:folder/.neyvia-notes.json emits:notes.changed ui:Notes undo:notes.pin(path pinned:previous.pinned) -- note bytes unchanged
C notes.pin saved: notes.read(path).pinned==pinned
A notes.open(path:path) ~
I notes.open emits:notes.open ui:Notes undo:none -- the receipt does not prove the UI showed it
C notes.open exists: notes.read(path).path==path
A notes.folder(folder?:path) -> {folder:path exists:bool} ~
I notes.folder writes:setting.notes-folder undo:notes.folder(folder:previous.folder) -- creates the folder; never moves notes
C notes.folder saved: notes.folder().folder==folder

-- L2
C notes.write tagged(tag:tag): notes.read(path).tags has tag
J capture append|leave: "Add this dictated idea to the selected note, or leave the note unchanged?" -- idea is transcribed with a prose #tag; confirm the topic first
J replace-note replace|leave: "Does the proposed body keep what matters in the current note?" -- note bytes have no undo
P capture-tagged-idea(path:path idea:str tag:tag): b=notes.read(path); J capture=append; notes.write(path body:idea mode:append expectedModified:b.modified) C tagged
P write-and-pin(path:path body:str expectedModified:id): notes.read(path); J replace-note=replace; notes.write(path body expectedModified); notes.pin(path)
X notes.write status:conflict -> b=notes.read(path); merge the idea into b.body; retry with expectedModified:b.modified -- never drop the guard
X tag absent from tags -> write #tag in prose outside backticks and fences
X notes missing after notes.folder -> the folder change moved nothing; switch back or migrate chosen files
X note absent from notes.list -> check extension, hidden or _ dirs, 2MiB, 3000-file bound; then notes.read(path)
F mic recording, language routing, transcription -> dictation manual
F version history, note delete, multi-writer merge
Q dest "is this the note the idea belongs to?" -> notes.search(query:idea) blocks:notes.write
M notes "#tags inside code fences or link anchors never count" src:neyvia_notes_tools.py#TAG state:verified
V P capture-tagged-idea -> script why:"typed steps; a model only at J capture"
V J capture -> model:small why:"two options, note and idea in context"

-- runtime: observe, then act
K writers [Paul:Notes-app models:neyvia.notes] guard:expectedModified
S notes folder:"C:/Users/example/Neyvia Notes" exists total:3 @h1
E Ideas.md "Ideas" [cl,neyvia] 1790976200013753000 "Connected Language: one grammar for every layer. Manual-first tools save context." pinned
E "Night shift.md" "Night shift" [plan] 1790976200117229400 "T16 merged, T18 merged. Next: CL spec then parser."
E Groceries.md "Groceries" [] 1790976200064958100 "oat milk coffee"
S notes.tags [cl:1 neyvia:1 plan:1]
do notes.write(path:Ideas.md body:"Every action carries its checks and impact. #cl" mode:append expectedModified:1790976200013753000)
R notes.write ok @r1 +cas +saved
D notes.items[Ideas.md] modified=1790976200225377900 excerpt="Connected Language: one grammar for every layer. Manual-first tools save context. Every action carries its checks and impact."
I notes.write writes:"C:/Users/example/Neyvia Notes/Ideas.md" emits:notes.changed
