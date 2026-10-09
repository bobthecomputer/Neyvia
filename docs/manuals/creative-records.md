<!-- Generated from manuals/cl/creative-records.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# creative-records

## local-records
CL 1
L creative-records v1 -- Task proposals and reported representation experiments
T t1 json:"{\"type\":\"array\"}"
T t2 json:"{\"type\":\"object\"}"
A situation.define(workId:str task:str constraints?:t1 acceptance?:t1 expectedRevision?:int) -> t2 ! -- Persist the exact scoped proposal or unverified observation and conserve unrelated records
F verify-situation-define "No authored observer check is bound to situation.define" -> ask operator blocks:situation.define
A attention.create(workId:str arguments:t2) -> t2 ! -- Persist the exact scoped proposal or unverified observation and conserve unrelated records
F verify-attention-create "No authored observer check is bound to attention.create" -> ask operator blocks:attention.create
A attention.observe(workId:str arguments:t2) -> t2 ! -- Persist the exact scoped proposal or unverified observation and conserve unrelated records
F verify-attention-observe "No authored observer check is bound to attention.observe" -> ask operator blocks:attention.observe
P record-situation-define(workId:str task:str constraints:t1 acceptance:t1 expectedRevision:int):saved=situation.define(acceptance:acceptance constraints:constraints expectedRevision:expectedRevision task:task workId:workId) -- Save an exact task proposal, constraints and acceptance criteria under one work identity
V P record-situation-define -> script why:"typed manual runner; stops at every judgement"
P record-attention-create(workId:str arguments:t2):saved=attention.create(arguments:arguments workId:workId) -- Freeze a bounded local representation experiment; no model call occurs
V P record-attention-create -> script why:"typed manual runner; stops at every judgement"
P record-attention-observe(workId:str arguments:t2):saved=attention.observe(arguments:arguments workId:workId) -- Append one caller-reported API observation without claiming it was independently verified
V P record-attention-observe -> script why:"typed manual runner; stops at every judgement"
X A caller-reported route or response is mistaken for independently verified model evidence -> Treat attention observations as unverified data; run and cite a separate authorized provider evaluation.
X A situation revision or attention experiment ID is stale -> Read the selected owner state and retry with the current revision or a fresh experiment ID.
F These records do not launch a provider, prove model improvement, or verify API responses.
F Browser action, operator preference, and public promotion need separate authority and observation.
M creative-records "Use one workId consistently. Keep task contracts explicit and budget representation experiments." src:"authored manual" state:verified
M creative-records "Preserve failed, missing, or route-mismatched observations rather than promoting a preferred variant." src:"authored manual" state:verified
