CL 1
L adaptive-work v1 -- Authored executable manual
-- @manual {"chapters":{"work":{"title":"Adaptive work: focus, open problems, and protected constraints"}},"clVersion":"1.1","id":"adaptive-work","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"work.constraint":"t1","work.focus":"t1","work.problem":"t2","work.update_problem":"t3"},"tool_metadata":{"work.constraint":{"mutability_class":"artifact_write"},"work.focus":{"mutability_class":"artifact_write"},"work.problem":{"mutability_class":"artifact_write"},"work.update_problem":{"mutability_class":"artifact_write"}}}
T t1 json:"{\"type\":\"object\",\"properties\":{\"workId\":{\"type\":\"string\"},\"text\":{\"type\":\"string\"}},\"required\":[\"workId\",\"text\"],\"allOf\":[{\"properties\":{\"workId\":{\"not\":{\"enum\":[\"\"]}},\"text\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t2 json:"{\"type\":\"object\",\"properties\":{\"workId\":{\"type\":\"string\"},\"text\":{\"type\":\"string\"},\"blocker\":{\"type\":\"string\"}},\"required\":[\"workId\",\"text\"],\"allOf\":[{\"properties\":{\"workId\":{\"not\":{\"enum\":[\"\"]}},\"text\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t3 json:"{\"type\":\"object\",\"properties\":{\"workId\":{\"type\":\"string\"},\"problemId\":{\"type\":\"string\"},\"status\":{\"type\":\"string\",\"enum\":[\"open\",\"blocked\",\"resolved\"]},\"need\":{\"type\":\"string\",\"enum\":[\"inspect\",\"generate\",\"implement\",\"compare\",\"test\",\"retrieve\",\"reflect\"]}},\"required\":[\"workId\",\"problemId\",\"status\",\"need\"],\"allOf\":[{\"properties\":{\"workId\":{\"not\":{\"enum\":[\"\"]}},\"problemId\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t4 json:"{\"type\":\"object\"}"
T t5{workId:str text:str ..}
T t6{workId:str text:str blocker:str ..}
T t7{workId:str problemId:str status:json:"{\"type\":\"string\",\"enum\":[\"open\",\"blocked\",\"resolved\"]}" need:json:"{\"type\":\"string\",\"enum\":[\"inspect\",\"generate\",\"implement\",\"compare\",\"test\",\"retrieve\",\"reflect\"]}" ..}
L adaptive-work.work v1 -- Adaptive work: focus, open problems, and protected constraints
-- @record {"chapter":"work","data":{"effect":"Persist one revision and matching event for this work identity; conserve other fields","pre":"Safe work identity and exact selected input; persisted state must be intact","returns":{"$cl_type":"t4"},"reversible":false,"schema":"work.focus","tool":"work.focus"},"key":"focus","section":"actions"}
A work.focus(workId:str text:str) -> json:"{\"type\":\"object\"}" ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-focus "No authored observer check is bound to work.focus" -> ask operator blocks:work.focus
-- @record {"chapter":"work","data":{"effect":"Persist one revision and matching event for this work identity; conserve other fields","pre":"Safe work identity and exact selected input; persisted state must be intact","returns":{"$cl_type":"t4"},"reversible":false,"schema":"work.problem","tool":"work.problem"},"key":"problem","section":"actions"}
A work.problem(workId:str text:str blocker?:str) -> json:"{\"type\":\"object\"}" ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-problem "No authored observer check is bound to work.problem" -> ask operator blocks:work.problem
-- @record {"chapter":"work","data":{"effect":"Persist one revision and matching event for this work identity; conserve other fields","pre":"Safe work identity and exact selected input; persisted state must be intact","returns":{"$cl_type":"t4"},"reversible":false,"schema":"work.constraint","tool":"work.constraint"},"key":"constraint","section":"actions"}
A work.constraint(workId:str text:str) -> json:"{\"type\":\"object\"}" ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-constraint "No authored observer check is bound to work.constraint" -> ask operator blocks:work.constraint
-- @record {"chapter":"work","data":{"effect":"Persist one revision and matching event for this work identity; conserve other fields","pre":"Safe work identity and exact selected input; persisted state must be intact","returns":{"$cl_type":"t4"},"reversible":false,"schema":"work.update_problem","tool":"work.update_problem"},"key":"update_problem","section":"actions"}
A work.update_problem(workId:str problemId:str status:json:"{\"type\":\"string\",\"enum\":[\"open\",\"blocked\",\"resolved\"]}" need:json:"{\"type\":\"string\",\"enum\":[\"inspect\",\"generate\",\"implement\",\"compare\",\"test\",\"retrieve\",\"reflect\"]}") -> json:"{\"type\":\"object\"}" ! -- Persist one revision and matching event for this work identity; conserve other fields
F verify-update_problem "No authored observer check is bound to work.update_problem" -> ask operator blocks:work.update_problem
-- @record {"chapter":"work","data":{"goal":"Set the current focus while preserving all earlier problems and constraints","inputs":{"$cl_type":"t5"},"steps":[{"action":"focus","args":{"text":{"$input":"text"},"workId":{"$input":"workId"}},"save":"changed"}]},"key":"record-focus","section":"procedures"}
P record-focus(workId:str text:str):changed=work.focus(text:text workId:workId) -- Set the current focus while preserving all earlier problems and constraints
V P record-focus -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"work","data":{"goal":"Record one unresolved problem and its blocker without claiming resolution","inputs":{"$cl_type":"t6"},"steps":[{"action":"problem","args":{"blocker":{"$input":"blocker"},"text":{"$input":"text"},"workId":{"$input":"workId"}},"save":"changed"}]},"key":"record-problem","section":"procedures"}
P record-problem(workId:str text:str blocker:str):changed=work.problem(blocker:blocker text:text workId:workId) -- Record one unresolved problem and its blocker without claiming resolution
V P record-problem -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"work","data":{"goal":"Preserve one explicit constraint across focus changes","inputs":{"$cl_type":"t5"},"steps":[{"action":"constraint","args":{"text":{"$input":"text"},"workId":{"$input":"workId"}},"save":"changed"}]},"key":"record-constraint","section":"procedures"}
P record-constraint(workId:str text:str):changed=work.constraint(text:text workId:workId) -- Preserve one explicit constraint across focus changes
V P record-constraint -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"work","data":{"goal":"Change the selected existing problem status and next need","inputs":{"$cl_type":"t7"},"steps":[{"action":"update_problem","args":{"need":{"$input":"need"},"problemId":{"$input":"problemId"},"status":{"$input":"status"},"workId":{"$input":"workId"}},"save":"changed"}]},"key":"record-update-problem","section":"procedures"}
P record-update-problem(workId:str problemId:str status:json:"{\"type\":\"string\",\"enum\":[\"open\",\"blocked\",\"resolved\"]}" need:json:"{\"type\":\"string\",\"enum\":[\"inspect\",\"generate\",\"implement\",\"compare\",\"test\",\"retrieve\",\"reflect\"]}"):changed=work.update_problem(need:need problemId:problemId status:status workId:workId) -- Change the selected existing problem status and next need
V P record-update-problem -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"work","data":{"failure":"A problem ID is absent or belongs to another work identity","recovery":"Inspect that work identity and choose an existing problem ID before updating."},"key":"0","section":"pitfalls"}
X A problem ID is absent or belongs to another work identity -> Inspect that work identity and choose an existing problem ID before updating.
-- @record {"chapter":"work","data":{"failure":"The saved state has an integrity mismatch","recovery":"Stop; inspect the corrupt file before any new write or recovery."},"key":"1","section":"pitfalls"}
X The saved state has an integrity mismatch -> Stop; inspect the corrupt file before any new write or recovery.
-- @record {"chapter":"work","data":"work.state initializes an absent JSON store, so it is not a pure CL observer.","key":"0","section":"frontier"}
F work.state initializes an absent JSON store, so it is not a pure CL observer.
-- @record {"chapter":"work","data":"The state records reported work; a saved focus or problem does not prove task quality.","key":"1","section":"frontier"}
F The state records reported work; a saved focus or problem does not prove task quality.
-- @record {"chapter":"work","data":"Use the same workId for related turns. The effect check binds to its JSON revision and event.","key":"0","section":"guidance"}
M adaptive-work "Use the same workId for related turns. The effect check binds to its JSON revision and event." src:"authored manual" state:verified
-- @record {"chapter":"work","data":"Keep constraints even when focus changes; resolve problems only by exact problem ID.","key":"1","section":"guidance"}
M adaptive-work "Keep constraints even when focus changes; resolve problems only by exact problem ID." src:"authored manual" state:verified
