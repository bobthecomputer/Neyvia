<!-- Generated from manuals/cl/C7e-c7d-control.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# C7e-c7d-control

## campaign
CL 1
L C7e-c7d-control v1 -- Generated c7d-control-family edge contracts
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"integer\",\"enum\":[48741,48742,48743,48744,48745,48746,48747,48748,48749,48871,48872,48873,48874,48875,48876,48877,48878,48879,48880,48881,48882,48883,48884,48885,48886,48887,48888,48889,48941,48942,48943,48944,48945,48946,48947,48948,48949,48950,48951,48952,48953,48954,48955,48956,48957,48958,48959,48960,48961,48962,48963,48964,48965,48966,48967,48968,48969,48970,48971,48972,48973,48974,48975,48976,48977,48978,48979,48980,48981,48982,48983,48984,48985,48986,48987,48988,48989,48990,48991,48992,48993,48994,48995,48996,48997,48998,48999,48731,48732,48733,48734,48735,48736,48737,48738,48739]}"
T t3 json:"{\"type\":\"array\",\"items\":{\"type\":\"string\"},\"minItems\":1,\"uniqueItems\":true}"
S C7e-c7d-control.latest:t1=neyvia.verify.edges.status(family:"c7d-control")
A neyvia.verify.edges(port:t2 schemaOnly?:bool semanticFixtures?:bool families?:t3) -> t1 -- Generate and execute the existing c7d-control fixture builder cases and persist a source-bound receipt
C neyvia.verify.edges family-passed:neyvia.verify.edges.status(family:"c7d-control") .allApplicableCasesPassed == true
A neyvia.verify.edges.status(family?:str) -> t1 -- Read actual c7d-control-family case counts, outcomes, source freshness and receipt integrity
C neyvia.verify.edges.status fresh:neyvia.verify.edges.status(family:"c7d-control") .sourceCurrent == true
C neyvia.verify.edges.status intact:neyvia.verify.edges.status(family:"c7d-control") .receiptIntact == true
C neyvia.verify.edges.status family-passed:neyvia.verify.edges.status(family:"c7d-control") .allApplicableCasesPassed == true
C neyvia.verify.edges.status fresh:neyvia.verify.edges.status(family:"c7d-control") .sourceCurrent == true
C neyvia.verify.edges.status intact:neyvia.verify.edges.status(family:"c7d-control") .receiptIntact == true
P run-family(port:t2):campaign=neyvia.verify.edges(families:["c7d-control"] port:port schemaOnly:false semanticFixtures:true) C family-passed; family-status=neyvia.verify.edges.status(family:"c7d-control") C fresh; receipt-status=neyvia.verify.edges.status(family:"c7d-control") C intact -- Execute the existing c7d-control-family builder; its actual nonempty family rows all pass against current source and an intact receipt
V P run-family -> script why:"typed manual runner; stops at every judgement"
X Any actual c7d-control-family case is missing, blocked or failed -> Preserve the receipt and inspect its familyCounts and failed rows; do not infer coverage from campaign completion
X The source changes or the receipt is damaged -> Retain the receipt as historical evidence and rerun the family campaign against current source
F This procedure covers only generated c7d-control-family builder rows; other edge families and rendered application behavior remain separate
M C7e-c7d-control "Use familyCases and familyCounts from the source-bound receipt for exact generated case and outcome totals" src:"authored manual" state:verified
M C7e-c7d-control "No credentials, external providers, NAS, live services, downloads or release promotion" src:"authored manual" state:verified
