CL 1.1
-- Files layer. Same sources and real run as 1.0 (../../examples/files.cl, ../../examples/today/files.*).

-- L0
L files v2 -- Home/workspace/project files; Recycle Bin; undo

-- L1
P files.tidy(source, dest, tidy?: "move"|"leave") G: files.stat(dest).name == base(source)
P files.undo_tidy(source, dest, retain?: "keep"|"undo") G: files.stat(source) != null -- right after a move only
J tidy "move"|"leave": "Is this destination right for this item?"
J retain "keep"|"undo": "Keep the move or put the item back?"
A files.list(path?, showHidden?: bool) -> dir[name size modified openWith] -- no path: places; 2000-entry cap
A files.stat(path, preview?: bool) -> entry[name kind size modified mime preview]
A files.move(source, dest) ~ -- never overwrites; dest may be an existing folder
A files.mkdir(path) ~
A files.trash(path) ~ -- Recycle Bin only
A files.undo() ! -- one slot shared with Paul
X destination exists -> pick another name; never trash the collision

-- runtime
files.list(path="C:/Users/example/Projects/nx-cl/manuals")
R files.list ok h1
S files h1 "C:/Users/example/Projects/nx-cl/manuals" place="Home" #25 [name size modified openWith]
E "agents.manual.json" 6449 2026-10-02T21:12:47.817642Z "text"
E "autopilot.manual.json" 7083 2026-10-02T21:12:47.817642Z "text"
E "awareness.manual.json" 10686 2026-10-02T21:12:47.818644Z "text"
E "computer-use.manual.json" 26431 2026-10-02T21:12:47.820151Z "text"
E "conductor.manual.json" 10503 2026-10-02T21:12:47.821672Z "text"
E "cross-pc.manual.json" 22852 2026-10-02T21:12:47.821672Z "text"
E "design.manual.json" 85956 2026-10-02T21:22:19.741893Z "text"
E "dictation.manual.json" 11538 2026-10-02T21:12:47.825315Z "text"
E "files.manual.json" 12319 2026-10-02T21:12:47.827837Z "text"
E "game-dev.manual.json" 11259 2026-10-02T21:12:47.828452Z "text"
E "hill-climb.manual.json" 4680 2026-10-02T21:12:47.829459Z "text"
E "image-studio.manual.json" 15543 2026-10-02T21:12:47.830964Z "text"
E "manuals-next.manual.json" 19216 2026-10-02T21:12:47.831980Z "text"
E "mobile-studio.manual.json" 14433 2026-10-02T21:12:47.832973Z "text"
E "neyvia-reference.manual.json" 49628 2026-10-02T21:12:47.833973Z "text"
E "neyvia.manual.json" 62697 2026-10-02T21:22:19.734349Z "text"
E "notes.manual.json" 14309 2026-10-02T21:12:47.835972Z "text"
E "onboarding.manual.json" 14337 2026-10-02T21:12:47.837088Z "text"
E "outputs.manual.json" 13680 2026-10-02T21:12:47.837088Z "text"
E "pdf.manual.json" 15112 2026-10-02T21:12:47.838097Z "text"
E "perception.manual.json" 58263 2026-10-02T21:12:47.840606Z "text"
E "sidebar.manual.json" 10192 2026-10-02T21:12:47.841624Z "text"
E "tools-depth.manual.json" 17578 2026-10-02T21:12:47.842623Z "text"
E "working-with-paul.manual.json" 9045 2026-10-02T21:12:47.843622Z "text"
E "workspace.manual.json" 19254 2026-10-02T21:12:47.844621Z "text"
K agent "codex/cl" writing=["src/grant_agent/cl/", "scripts/cl_token_meter.py"] -- host: work board, shown because the next action is a mutation
run files.tidy(source="C:/ws/inbox/cl-benchmark-draft.md", dest="C:/ws/reports", tidy="move")
R files.tidy ok r1 +G
D -"C:/ws/inbox/cl-benchmark-draft.md"
D +"C:/ws/reports/cl-benchmark-draft.md" 22 2026-10-02T21:27:27.880078Z "text"
I files.move wrote=["C:/ws/inbox/cl-benchmark-draft.md", "C:/ws/reports/cl-benchmark-draft.md"] emitted="files.changed" undo="files.undo()"

-- host
A files.move(source:path=from dest:path=to) ~ -- agent names map to the tool's from/to (from is a Python keyword)
C files.move moved: files.stat(result.to).name == result.entry.name
C files.trash gone: files.stat(path) == null
C files.undo undone: (result.undone != "move" or files.stat(result.action.from) != null) and (result.undone != "mkdir" or files.stat(result.action.path) == null) and (result.undone != "trash" or files.stat(result.action.path) != null)
P files.tidy(source:path dest:path tidy?:move|leave): files.stat(path=source); J tidy="move"; files.move(source=source dest=dest)
P files.undo_tidy(source:path dest:path retain?:keep|undo): files.stat(path=dest); J retain="undo"; files.undo()
-- ask/approval for Home and project places comes from the existing permission gate and appears as R ask + K approval.
