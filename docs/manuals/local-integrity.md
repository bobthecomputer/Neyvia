<!-- Generated from manuals/cl/local-integrity.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-integrity

## overview
CL 1
L local-integrity v1 -- Initialize local work and verify exact proof artifact bytes
T t1 json:"{\"type\":\"object\"}"
A work.state(workId:str) -> t1 ! -- Exact owning state persists, freshly independently reread
F verify-state "No authored observer check is bound to work.state" -> ask operator blocks:work.state
A semantic.proof.verify(proofId:str) -> t1 ! -- Exact owning state persists, freshly independently reread
F verify-verify "No authored observer check is bound to semantic.proof.verify" -> ask operator blocks:semantic.proof.verify
P state(workId:str):effect=work.state(workId:workId) -- Exact owning state persists, freshly independently reread
V P state -> script why:"typed manual runner; stops at every judgement"
P verify(proofId:str):effect=semantic.proof.verify(proofId:proofId) -- Exact owning state persists, freshly independently reread
V P verify -> script why:"typed manual runner; stops at every judgement"
F Artifact integrity does not establish a capsule semantic claim.
F work.state initializes absent stores and cannot be used as a pure goal observer.
