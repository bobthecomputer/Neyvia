CL 1
L local-integrity v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Initialize local work and verify exact proof artifact bytes"}},"clVersion":"1.1","id":"local-integrity","kind":"environment","schema":"neyvia.manual.v1","schemas":{"semantic.proof.verify":"t1","work.state":"t2"},"tool_metadata":{"semantic.proof.verify":{"mutability_class":"artifact_write"},"work.state":{"mutability_class":"artifact_write"}}}
T t1 json:"{\"type\":\"object\",\"properties\":{\"proofId\":{\"type\":\"string\"}},\"required\":[\"proofId\"],\"allOf\":[{\"properties\":{\"proofId\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t2 json:"{\"type\":\"object\",\"properties\":{\"workId\":{\"type\":\"string\"}},\"required\":[\"workId\"],\"allOf\":[{\"properties\":{\"workId\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t3 json:"{\"type\":\"object\"}"
T t4{workId:str ..}
T t5{proofId:str ..}
L local-integrity.overview v1 -- Initialize local work and verify exact proof artifact bytes
-- @record {"chapter":"overview","data":{"effect":"Exact owning state persists, freshly independently reread","pre":"Selected safe workspace identity and intact source bytes","returns":{"$cl_type":"t3"},"reversible":false,"schema":"work.state","tool":"work.state"},"key":"state","section":"actions"}
A work.state(workId:str) -> json:"{\"type\":\"object\"}" ! -- Exact owning state persists, freshly independently reread
F verify-state "No authored observer check is bound to work.state" -> ask operator blocks:work.state
-- @record {"chapter":"overview","data":{"effect":"Exact owning state persists, freshly independently reread","pre":"Selected safe workspace identity and intact source bytes","returns":{"$cl_type":"t3"},"reversible":false,"schema":"semantic.proof.verify","tool":"semantic.proof.verify"},"key":"verify","section":"actions"}
A semantic.proof.verify(proofId:str) -> json:"{\"type\":\"object\"}" ! -- Exact owning state persists, freshly independently reread
F verify-verify "No authored observer check is bound to semantic.proof.verify" -> ask operator blocks:semantic.proof.verify
-- @record {"chapter":"overview","data":{"goal":"Exact owning state persists, freshly independently reread","inputs":{"$cl_type":"t4"},"steps":[{"action":"state","args":{"workId":{"$input":"workId"}},"save":"effect"}]},"key":"state","section":"procedures"}
P state(workId:str):effect=work.state(workId:workId) -- Exact owning state persists, freshly independently reread
V P state -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Exact owning state persists, freshly independently reread","inputs":{"$cl_type":"t5"},"steps":[{"action":"verify","args":{"proofId":{"$input":"proofId"}},"save":"effect"}]},"key":"verify","section":"procedures"}
P verify(proofId:str):effect=semantic.proof.verify(proofId:proofId) -- Exact owning state persists, freshly independently reread
V P verify -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":"Artifact integrity does not establish a capsule semantic claim.","key":"0","section":"frontier"}
F Artifact integrity does not establish a capsule semantic claim.
-- @record {"chapter":"overview","data":"work.state initializes absent stores and cannot be used as a pure goal observer.","key":"1","section":"frontier"}
F work.state initializes absent stores and cannot be used as a pure goal observer.
