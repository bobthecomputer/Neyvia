<!-- Generated from manuals/cl/local-mechanisms.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-mechanisms

## mechanisms
CL 1
L local-mechanisms v1 -- Frozen artifact competition and lossless context compaction
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"object\",\"minProperties\":2,\"maxProperties\":8,\"additionalProperties\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":4096}}"
T t3 json:"{\"type\":\"array\",\"minItems\":2,\"maxItems\":8,\"uniqueItems\":true,\"items\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120}}"
T t4 json:"{\"type\":\"array\",\"minItems\":1,\"maxItems\":12,\"uniqueItems\":true,\"items\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120}}"
T t5{kind:json:"{\"type\":\"string\",\"enum\":[\"json_numeric\",\"image\",\"trace_timing\"]}" key?:str#1.. max?:num maxMeanMs?:json:"{\"type\":\"number\",\"minimum\":0}" minWidth?:0.. minHeight?:0.. maxBytes?:0..}
A context.compact(sessionId:str focus?:str targetRatio?:0.05..0.8 maxContextTokens?:1000..2000000) -> t1 ! -- Freeze isolated candidates, measure all candidates against identical criteria, or archive older context without losing original evidence
F verify-context-compact "No authored observer check is bound to context.compact" -> ask operator blocks:context.compact
A lab.compare(identity:str targets:t2 workId:str) -> t1 ! -- Freeze isolated candidates, measure all candidates against identical criteria, or archive older context without losing original evidence
F verify-lab-compare "No authored observer check is bound to lab.compare" -> ask operator blocks:lab.compare
A lab.competition(identity:str source:str candidates:t3 instruments:t4 workId:str) -> t1 ! -- Freeze isolated candidates, measure all candidates against identical criteria, or archive older context without losing original evidence
F verify-lab-competition "No authored observer check is bound to lab.competition" -> ask operator blocks:lab.competition
A lab.instrument(identity:str spec:t5) -> t1 ! -- Freeze isolated candidates, measure all candidates against identical criteria, or archive older context without losing original evidence
F verify-lab-instrument "No authored observer check is bound to lab.instrument" -> ask operator blocks:lab.instrument
P verify-context-compact(sessionId:str focus:str targetRatio:0.05..0.8 maxContextTokens:1000..2000000):saved=context.compact(focus:focus maxContextTokens:maxContextTokens sessionId:sessionId targetRatio:targetRatio) -- Archive older active context without deleting it, protect recent and pinned evidence, and write a compaction receipt.
V P verify-context-compact -> script why:"typed manual runner; stops at every judgement"
P verify-lab-compare(identity:str targets:t2 workId:str):saved=lab.compare(identity:identity targets:targets workId:workId) -- Measure every competition candidate with the same frozen instruments; never automatically promote
V P verify-lab-compare -> script why:"typed manual runner; stops at every judgement"
P verify-lab-competition(identity:str source:str candidates:t3 instruments:t4 workId:str):saved=lab.competition(candidates:candidates identity:identity instruments:instruments source:source workId:workId) -- Create isolated candidate source snapshots under one frozen measurement contract
V P verify-lab-competition -> script why:"typed manual runner; stops at every judgement"
P verify-lab-instrument(identity:str spec:t5):saved=lab.instrument(identity:identity spec:spec) -- Freeze an existing quality instrument for matched artifact evaluation
V P verify-lab-instrument -> script why:"typed manual runner; stops at every judgement"
X One failed candidate is omitted from a comparison -> Measure every candidate named by the frozen contract and retain failed criteria.
X A compacted receipt hides lost instructions or original messages -> Freshly compare every old ledger row; protected content stays active and archived content stays retrievable.
F A frozen local artifact measurement proves its declared criterion, not general model improvement.
F Candidate promotion and provider/model execution require their own authority and real journey.
M local-mechanisms "Use new competition identities; isolated byte snapshots preserve the original source." src:"authored manual" state:verified
M local-mechanisms "Compaction needs an active bounded ledger. An empty ledger is refused rather than credited as an effect." src:"authored manual" state:verified
