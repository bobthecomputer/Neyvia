CL 1
L local-evolver v1 -- Authored executable manual
-- @manual {"chapters":{"evolution":{"title":"Frozen local manual compression"}},"clVersion":"1.1","id":"local-evolver","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"neyvia.evolver.run":"t1"},"tool_metadata":{"neyvia.evolver.run":{"mutability_class":"external_action"}}}
T t1{domain:json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}" requestId:str#1.. maxTrials?:1..2 ..}
T t2 json:"{\"type\":\"object\"}"
T t3{domain:json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}" requestId:str#1.. ..}
L local-evolver.evolution v1 -- Frozen local manual compression
-- @record {"chapter":"evolution","data":{"effect":"Run real manual_json_local_v1 parse, compiler, roundtrip and token measurements on matched seeded cases","pre":"Owned root and request identity; installed offline Rust engine; actual frozen manual files; current policy permits managed child processes","returns":{"$cl_type":"t2"},"reversible":false,"schema":"neyvia.evolver.run","tool":"neyvia.evolver.run"},"key":"run","section":"actions"}
A neyvia.evolver.run(domain:json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}" requestId:str#1.. maxTrials?:1..2) -> json:"{\"type\":\"object\"}" ! -- Run real manual_json_local_v1 parse, compiler, roundtrip and token measurements on matched seeded cases
F verify-run "No authored observer check is bound to neyvia.evolver.run" -> ask operator blocks:neyvia.evolver.run
-- @record {"chapter":"evolution","data":{"goal":"Finish a real frozen paired lossless compression trial, reconfirm on two fresh heldout panels, and update the local Pareto front","inputs":{"$cl_type":"t3"},"steps":[{"action":"run","args":{"domain":{"$input":"domain"},"maxTrials":1,"requestId":{"$input":"requestId"}},"save":"saved"}]},"key":"verify-local-manual-evolution","section":"procedures"}
P verify-local-manual-evolution(domain:json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}" requestId:str#1..):saved=neyvia.evolver.run(domain:domain maxTrials:1 requestId:requestId) -- Finish a real frozen paired lossless compression trial, reconfirm on two fresh heldout panels, and update the local Pareto front
V P verify-local-manual-evolution -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"evolution","data":{"failure":"A queued job or synthetic score is called an evaluated improvement","recovery":"Wait for actual parse/compiled artifacts; compare current bytes, paired seeds, frozen panels and counted engine trials."},"key":"0","section":"pitfalls"}
X A queued job or synthetic score is called an evaluated improvement -> Wait for actual parse/compiled artifacts; compare current bytes, paired seeds, frozen panels and counted engine trials.
-- @record {"chapter":"evolution","data":{"failure":"Compression removes instructions or protected checks","recovery":"Retain the rejected candidate; exact semantic and compiler roundtrip gates prevent promotion."},"key":"1","section":"pitfalls"}
X Compression removes instructions or protected checks -> Retain the rejected candidate; exact semantic and compiler roundtrip gates prevent promotion.
-- @record {"chapter":"evolution","data":"manual_json_local_v1 measures lossless JSON compression, not model task accuracy.","key":"0","section":"frontier"}
F manual_json_local_v1 measures lossless JSON compression, not model task accuracy.
-- @record {"chapter":"evolution","data":"Other domain routes retain their named GPT-6 Luna transport and need separate matched provider evaluations.","key":"1","section":"frontier"}
F Other domain routes retain their named GPT-6 Luna transport and need separate matched provider evaluations.
-- @record {"chapter":"evolution","data":"No models or downloads are used in this named local domain.","key":"0","section":"guidance"}
M local-evolver "No models or downloads are used in this named local domain." src:"authored manual" state:verified
-- @record {"chapter":"evolution","data":"Reuse requestId after interruptions; frozen judges and manual inputs cannot be changed inside an established domain.","key":"1","section":"guidance"}
M local-evolver "Reuse requestId after interruptions; frozen judges and manual inputs cannot be changed inside an established domain." src:"authored manual" state:verified
-- @record {"chapter":"evolution","data":"Local-only blocks all managed children, including this offline Rust engine; preserve that policy.","key":"2","section":"guidance"}
M local-evolver "Local-only blocks all managed children, including this offline Rust engine; preserve that policy." src:"authored manual" state:verified
