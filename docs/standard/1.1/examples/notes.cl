CL 1.1
-- Notes layer. Same sources and same real run as 1.0 (../../examples/notes.cl, ../../examples/today/notes.*).
-- Sections: L0 (always loaded), L1 (help("notes") / first touch), runtime (model-facing), host (never sent to the model).

-- L0
L notes v2 -- Markdown notes: search, #tags, pins, guarded writes

-- L1
P notes.capture(path, text, capture?: "append"|"leave") G: text in notes.read(path).body
P notes.replace(path, body, replace?: "replace"|"leave") G: notes.read(path).body == body
P notes.write_and_pin(path, body) G: notes.read(path).body == body and notes.read(path).pinned
J capture "append"|"leave": "Add this idea to this note?"
J replace "replace"|"leave": "Does the new body keep what matters in the note?"
A notes.list(query?, tag?, limit?: 1..500) -> notes[path title tags pinned]
A notes.search(query, limit?: 1..500) -> notes[path title tags pinned snippet]
A notes.read(path) -> note[path title tags pinned body]
A notes.write(body, path?, title?, mode?: "replace"|"append") -> note ! -- no path: new file named from title
A notes.pin(path, pinned?: bool = true) ~
A notes.open(path) ~
A notes.folder(folder?) ~ -- never moves notes
X tag missing from tags -> write #tag in prose, outside `code`

-- runtime
notes.list()
R notes.list ok h1
S notes h1 #3 [path title tags pinned]
E "Ideas.md" "Ideas" ["cl","neyvia"] true
E "Night shift.md" "Night shift" ["plan"] false
E "Groceries.md" "Groceries" [] false
run notes.capture(path="Ideas.md", text="Every action carries its checks and impact. #cl", capture="append")
R notes.capture ok r1 +G
D notes["Ideas.md"] excerpt="Connected Language: one grammar for every layer. Manual-first tools save context. Every action carries its checks and impact."
I notes.write wrote="C:/Users/example/Neyvia Notes/Ideas.md" emitted="notes.changed" undo=none
done("Appended the idea to Ideas.md")
R done ok +G

-- host
A notes.write(body:str path?:path title?:str mode?:replace|append expectedModified=auto(notes.read(path).modified)) -> note !
C notes.write saved: body in notes.read(path).body
C notes.write cas: result.status != "conflict"
C notes.pin saved: notes.read(path).pinned == pinned
P notes.capture(path:path text:str capture?:append|leave): notes.read(path); J capture="append"; notes.write(path=path body=text mode="append")
P notes.replace(path:path body:str replace?:replace|leave): notes.read(path); J replace="replace"; notes.write(path=path body=body)
P notes.write_and_pin(path:path body:str): notes.write(path=path body=body); notes.pin(path=path)
X notes.write status="conflict" -> host re-reads, refreshes expectedModified, returns D of the other writer's change
-- I lines are generated at action time from the impact map (neyvia.impact), bus events and the work board.
