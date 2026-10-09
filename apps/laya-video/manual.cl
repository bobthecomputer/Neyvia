CL 1
L laya-video v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"LAYA edits video by itself: a CL brief becomes a first draft from real captures, the shared Scene core judges the rendered file and keeps only fixes that remove findings; A/B votes become personal taste episodes."}},"clVersion":"1.1","id":"laya-video","kind":"environment","schema":"neyvia.manual.v1","schemas":{"neyvia.mod.laya_video.draft":"t1","neyvia.mod.laya_video.improve":"t3","neyvia.mod.laya_video.inspect":"t2","neyvia.mod.laya_video.verify":"t5","neyvia.mod.laya_video.vote":"t4"},"tool_metadata":{"neyvia.mod.laya_video.draft":{"mutability_class":"artifact_write"},"neyvia.mod.laya_video.improve":{"mutability_class":"artifact_write"},"neyvia.mod.laya_video.inspect":{"mutability_class":"artifact_write"},"neyvia.mod.laya_video.verify":{"mutability_class":"read"},"neyvia.mod.laya_video.vote":{"mutability_class":"artifact_write"}}}
T t1{brief:str#..4000 out:str#..4000}
T t2{project:str#..4000 quality?:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"preview\",\"master\"]}"}
T t3{project:str#..4000 rounds?:json:"{\"type\":\"number\",\"minimum\":1,\"maximum\":24}" maxSeconds?:json:"{\"type\":\"number\",\"minimum\":1,\"maximum\":300}" allowedFixes?:[str#..4000]}
T t4{a:str#..4000 b:str#..4000 winner:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"a\",\"b\"]}" user:str#1..4000 reason?:str#..4000 voteId?:str#..4000}
T t5{}
T t6 json:"{\"type\":\"object\"}"
T t7 json:"{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"
L laya-video.overview v1 -- LAYA edits video by itself: a CL brief becomes a first draft from real captures, the shared Scene core judges the rendered file and keeps only fixes that remove findings; A/B votes become personal taste episodes.
-- @record {"chapter":"overview","data":{"effect":"Assemble the first draft EDL from a CL brief and real captures.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.laya_video.draft","tool":"neyvia.mod.laya_video.draft"},"key":"mod.laya_video.draft","section":"actions"}
A neyvia.mod.laya_video.draft(brief:str#..4000 out:str#..4000) -> json:"{\"type\":\"object\"}" ! -- Assemble the first draft EDL from a CL brief and real captures.
F verify-mod-laya_video-draft "No authored observer check is bound to neyvia.mod.laya_video.draft" -> ask operator blocks:neyvia.mod.laya_video.draft
-- @record {"chapter":"overview","data":{"effect":"Render and transcribe a project, then judge it with the shared core.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.laya_video.inspect","tool":"neyvia.mod.laya_video.inspect"},"key":"mod.laya_video.inspect","section":"actions"}
A neyvia.mod.laya_video.inspect(project:str#..4000 quality?:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"preview\",\"master\"]}") -> json:"{\"type\":\"object\"}" ! -- Render and transcribe a project, then judge it with the shared core.
F verify-mod-laya_video-inspect "No authored observer check is bound to neyvia.mod.laya_video.inspect" -> ask operator blocks:neyvia.mod.laya_video.inspect
-- @record {"chapter":"overview","data":{"effect":"Guarded improve rounds: each named EDL fix is kept only on a strict finding reduction.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.laya_video.improve","tool":"neyvia.mod.laya_video.improve"},"key":"mod.laya_video.improve","section":"actions"}
A neyvia.mod.laya_video.improve(project:str#..4000 rounds?:json:"{\"type\":\"number\",\"minimum\":1,\"maximum\":24}" maxSeconds?:json:"{\"type\":\"number\",\"minimum\":1,\"maximum\":300}" allowedFixes?:[str#..4000]) -> json:"{\"type\":\"object\"}" ! -- Guarded improve rounds: each named EDL fix is kept only on a strict finding reduction.
F verify-mod-laya_video-improve "No authored observer check is bound to neyvia.mod.laya_video.improve" -> ask operator blocks:neyvia.mod.laya_video.improve
-- @record {"chapter":"overview","data":{"effect":"Record a person's A/B preference between two cuts as personal episodes.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.mod.laya_video.vote","tool":"neyvia.mod.laya_video.vote"},"key":"mod.laya_video.vote","section":"actions"}
A neyvia.mod.laya_video.vote(a:str#..4000 b:str#..4000 winner:json:"{\"type\":\"string\",\"maxLength\":4000,\"enum\":[\"a\",\"b\"]}" user:str#1..4000 reason?:str#..4000 voteId?:str#..4000) -> json:"{\"type\":\"object\"}" ! -- Record a person's A/B preference between two cuts as personal episodes.
F verify-mod-laya_video-vote "No authored observer check is bound to neyvia.mod.laya_video.vote" -> ask operator blocks:neyvia.mod.laya_video.vote
-- @record {"chapter":"overview","data":{"effect":"Replay the recorded launch-cut proof against the laya-video CL contracts.","pre":"Selected workspace; the mod is installed, enabled and its local tool is present","returns":{"$cl_type":"t6"},"reversible":true,"schema":"neyvia.mod.laya_video.verify","tool":"neyvia.mod.laya_video.verify"},"key":"mod.laya_video.verify","section":"actions"}
A neyvia.mod.laya_video.verify() -> json:"{\"type\":\"object\"}" -- Replay the recorded launch-cut proof against the laya-video CL contracts.
C neyvia.mod.laya_video.verify verified:neyvia.mod.laya_video.verify() .passed == true
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"passed","value":true},"tool":"neyvia.mod.laya_video.verify"},"key":"verified","section":"checks"}
C neyvia.mod.laya_video.verify verified:neyvia.mod.laya_video.verify() .passed == true
-- @record {"chapter":"overview","data":{"goal":"Run the real round trip and check its outcome contracts","inputs":{"$cl_type":"t7"},"steps":[{"action":"mod.laya_video.verify","args":{},"check":"verified","save":"verified"}]},"key":"verify-laya-video","section":"procedures"}
P verify-laya-video():verified=neyvia.mod.laya_video.verify() C verified -- Run the real round trip and check its outcome contracts
V P verify-laya-video -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"failure":"The local tool is missing","recovery":"Build or point the NEYVIA_* path at it; the action refuses rather than downloading anything."},"key":"0","section":"pitfalls"}
X The local tool is missing -> Build or point the NEYVIA_* path at it; the action refuses rather than downloading anything.
-- @record {"chapter":"overview","data":{"failure":"A render exists but is wrong","recovery":"Read the outcome block (duration, frames, black/frozen runs, clipping); never call a render good from its exit code."},"key":"1","section":"pitfalls"}
X A render exists but is wrong -> Read the outcome block (duration, frames, black/frozen runs, clipping); never call a render good from its exit code.
-- @record {"chapter":"overview","data":"Renders take minutes on a loaded machine; each improve round is one render plus measurement.","key":"0","section":"frontier"}
F Renders take minutes on a loaded machine; each improve round is one render plus measurement.
-- @record {"chapter":"overview","data":"Votes are only ever cast by a person.","key":"1","section":"frontier"}
F Votes are only ever cast by a person.
-- @record {"chapter":"overview","data":"Write a brief as CL (S length/aspect/music/captions/must/story lines, C must-hold lines), then draft, improve and inspect at quality master.","key":"0","section":"guidance"}
M laya-video "Write a brief as CL (S length/aspect/music/captions/must/story lines, C must-hold lines), then draft, improve and inspect at quality master." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"The predicates, their measured facts and named fixes are in manuals/cl/laya-video.cl; every fix edits only edl.json.","key":"1","section":"guidance"}
M laya-video "The predicates, their measured facts and named fixes are in manuals/cl/laya-video.cl; every fix edits only edl.json." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Paul's taste: vote between two cuts; the vote is a personal episode, effective on the next similar edit.","key":"2","section":"guidance"}
M laya-video "Paul's taste: vote between two cuts; the vote is a personal episode, effective on the next similar edit." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Installs switched off from Marketplace > Apps & mods; read this manual and the declared permissions, then enable it.","key":"3","section":"guidance"}
M laya-video "Installs switched off from Marketplace > Apps & mods; read this manual and the declared permissions, then enable it." src:"authored manual" state:verified
