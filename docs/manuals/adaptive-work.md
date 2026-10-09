<!-- Generated from manuals/cl/adaptive-work.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# adaptive-work

## work
CL 1
L adaptive-work v1 -- Adaptive work: focus, open problems, and protected constraints
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"open\",\"blocked\",\"resolved\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"inspect\",\"generate\",\"implement\",\"compare\",\"test\",\"retrieve\",\"reflect\"]}"
A work.focus(workId:str text:str) -> t1 ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-focus "No authored observer check is bound to work.focus" -> ask operator blocks:work.focus
A work.problem(workId:str text:str blocker?:str) -> t1 ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-problem "No authored observer check is bound to work.problem" -> ask operator blocks:work.problem
A work.constraint(workId:str text:str) -> t1 ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-constraint "No authored observer check is bound to work.constraint" -> ask operator blocks:work.constraint
A work.update_problem(workId:str problemId:str status:t2 need:t3) -> t1 ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-update_problem "No authored observer check is bound to work.update_problem" -> ask operator blocks:work.update_problem
P record-focus(workId:str text:str):changed=work.focus(text:text workId:workId) -- Set the current focus while preserving all earlier problems and constraints
V P record-focus -> script why:"typed manual runner; stops at every judgement"
P record-problem(workId:str text:str blocker:str):changed=work.problem(blocker:blocker text:text workId:workId) -- Record one unresolved problem and its blocker without claiming resolution
V P record-problem -> script why:"typed manual runner; stops at every judgement"
P record-constraint(workId:str text:str):changed=work.constraint(text:text workId:workId) -- Preserve one explicit constraint across focus changes
V P record-constraint -> script why:"typed manual runner; stops at every judgement"
P record-update-problem(workId:str problemId:str status:t2 need:t3):changed=work.update_problem(need:need problemId:problemId status:status workId:workId) -- Change the selected existing problem status and next need
V P record-update-problem -> script why:"typed manual runner; stops at every judgement"
X A problem ID is absent or belongs to another work identity -> Inspect that work identity and choose an existing problem ID before updating.
X The saved state has an integrity mismatch -> Stop; inspect the corrupt file before any new write or recovery.
F work.state initializes an absent JSON store, so it is not a pure CL observer.
F The state records reported work; a saved focus or problem does not prove task quality.
M adaptive-work "Use the same workId for related turns. The effect check binds to its JSON revision and event." src:"authored manual" state:verified
M adaptive-work "Keep constraints even when focus changes; resolve problems only by exact problem ID." src:"authored manual" state:verified
