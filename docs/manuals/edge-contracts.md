<!-- Generated from manuals/cl/edge-contracts.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# edge-contracts

## campaign
CL 1
L edge-contracts v1 -- Generate and run edge cases
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"integer\",\"enum\":[48741,48742,48743,48744,48745,48746,48747,48748,48749,48871,48872,48873,48874,48875,48876,48877,48878,48879,48880,48881,48882,48883,48884,48885,48886,48887,48888,48889,48941,48942,48943,48944,48945,48946,48947,48948,48949,48950,48951,48952,48953,48954,48955,48956,48957,48958,48959,48960,48961,48962,48963,48964,48965,48966,48967,48968,48969,48970,48971,48972,48973,48974,48975,48976,48977,48978,48979,48980,48981,48982,48983,48984,48985,48986,48987,48988,48989,48990,48991,48992,48993,48994,48995,48996,48997,48998,48999,48731,48732,48733,48734,48735,48736,48737,48738,48739]}"
T t3 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"minItems\":1,\"uniqueItems\":true}"
S edge-contracts.latest:t1=neyvia.verify.edges.status()
A neyvia.verify.edges(port:t2 schemaOnly?:bool semanticFixtures?:bool families?:t3) -> t1 -- Generate native inputs and feature-family fixtures, reconcile every original semantic pair and persist a source-bound receipt
C neyvia.verify.edges passed:neyvia.verify.edges.status() .ok == true
A neyvia.verify.edges.status(family?:str) -> t1 -- Read receipt summary and verify source freshness
C neyvia.verify.edges.status fresh:neyvia.verify.edges.status() .sourceCurrent == true
C neyvia.verify.edges.status passed:neyvia.verify.edges.status() .ok == true
C neyvia.verify.edges.status fresh:neyvia.verify.edges.status() .sourceCurrent == true
P verify-admission(port:t2):campaign=neyvia.verify.edges(port:port schemaOnly:true semanticFixtures:false) C passed; fresh=neyvia.verify.edges.status() C fresh -- Every generated native input case agrees with its live schema after supported transport normalization
V P verify-admission -> script why:"typed manual runner; stops at every judgement"
P verify-local-edges(port:t2):campaign=neyvia.verify.edges(port:port schemaOnly:false semanticFixtures:true) C passed; fresh=neyvia.verify.edges.status() C fresh -- Generate and execute reviewed feature-family fixtures; report every unbound original semantic pair and its exact remaining requirement
V P verify-local-edges -> script why:"typed manual runner; stops at every judgement"
X A contract has no semantic fixture -> Keep its eight generated scenarios blocked; add a reviewed adapter and independent observer before claiming coverage
X Interrupted effect or stale source -> Inspect durable receipts and rerun a new isolated campaign; never replay an uncertain effect automatically
F Passing schema admission does not prove arbitrary tool execution, native apps, providers or rendered UI
F Complete semantic coverage requires every contract/category pair to have a real effect journey
M edge-contracts "Use the source-bound JSON receipt for exact payload digests, failures, coverage and baseline comparison" src:"authored manual" state:verified
M edge-contracts "No credentials, external providers, NAS, live services, downloads or release promotion" src:"authored manual" state:verified
