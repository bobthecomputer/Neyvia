<!-- Generated from manuals/cl/research.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# research

## workflow
CL 1
L research v1 -- Executable research method: chronological mechanism and measured quality
T t1 json:"{\"type\":\"object\",\"properties\":{\"accepted\":{\"type\":\"boolean\"},\"adherence\":{\"type\":\"number\"},\"fitness\":{\"type\":[\"number\",\"null\"]},\"errors\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"accepted\",\"adherence\",\"fitness\",\"errors\"],\"additionalProperties\":true}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"hill-climb\",\"creativity\",\"critique-review\",\"efficiency\",\"research\",\"design\"]}"
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"object\",\"additionalProperties\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\",\"minLength\":1},\"sha256\":{\"type\":\"string\",\"pattern\":\"^[a-f0-9]{64}$\"}},\"required\":[\"path\",\"sha256\"],\"additionalProperties\":false}}"
T t5 json:"{\"type\":\"number\",\"minimum\":0,\"maximum\":1}"
S research.adherence:t1=neyvia.workflow.check(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens)
A neyvia.workflow.check(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 -- Validate ordered workflow evidence
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
A neyvia.workflow.record(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 ! -- Persist a validated workflow receipt under the selected task root
C neyvia.workflow.record adhered:neyvia.workflow.check(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
P verify-and-record(report:t3 evidence:t4 outcomeQuality:t5 tokens:0..):verified=neyvia.workflow.check(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered; recorded=neyvia.workflow.record(evidence:evidence manual:"research" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered -- Verify defining workflow mechanism against host evidence and persist the acceptance receipt
V P verify-and-record -> script why:"typed manual runner; stops at every judgement"
J quality accept|revise:"Does the outcome satisfy the actual task, beyond recorded adherence?" -- Use an independent frozen host quality judge; self-reported quality is not evidence.
V J quality -> human:operator why:"explicit choice required"
X A model writes its own successful receipt, outcome score or token count -> The host supplies hash-bound local evidence files, independently judged quality and provider usage; invented IDs fail
F Executable adherence is necessary but not sufficient for semantic quality. Outcome quality belongs to a separate frozen task judge.
F Three paired tasks provide bounded evidence and cannot authorize statistical Evolver promotion.
M research "Start with one question that could change the implementation decision. Compare at least two concrete prior-art sources and what each establishes." src:"authored manual" state:verified
M research "State a prediction and a falsifier before testing. Prefer the smallest real test that discriminates the alternatives." src:"authored manual" state:verified
M research "The result must agree with measured success/failure, state limitations and separate observed facts from inference. A negative result is useful evidence." src:"authored manual" state:verified
M research "Report shape: {events:[{stage,data}],result:object}. Required chronological stages: question, prior-art, claim, test, result" src:"authored manual" state:verified
M research "question{question}; prior-art{sources:[{source,finding}]>=2}; claim{prediction,falsifier}; test{receipt}; result{supported:boolean,limitations:[strings]}. Test evidence has success:boolean." src:"authored manual" state:verified
M research "Public tool evidence is {ID:{path:task-root-relative receipt JSON,sha256:receipt SHA256}}. Pure host evaluator evidence maps IDs to loaded measurements. Public tool outcome quality is explicitly caller-scored, never automatically verified." src:"authored manual" state:verified
M research "Every data.receipt is a STRING naming a key in the host evidence mapping: for example {\"receipt\":\"measurement\"}. Never copy the receipt object or create a new ID. Public tool callers pass path/SHA descriptors separately; event receipt fields remain string IDs. Use the exact keys the current task supplied, not the example keys below." src:"authored manual" state:verified
M research "Conforming shape example (replace illustrative values, IDs and decision with the actual task/evidence; do not copy its outcome): {\"events\":[{\"stage\":\"question\",\"data\":{\"question\":\"does the candidate fix the observed failure\"}},{\"stage\":\"prior-art\",\"data\":{\"sources\":[{\"source\":\"owner source file\",\"finding\":\"defining mechanism implemented here\"},{\"source\":\"actual run receipt\",\"finding\":\"records the observed failure boundary\"}]}},{\"stage\":\"claim\",\"data\":{\"prediction\":\"candidate passes the frozen check\",\"falsifier\":\"same check fails on the candidate\"}},{\"stage\":\"test\",\"data\":{\"receipt\":\"test\"}},{\"stage\":\"result\",\"data\":{\"supported\":false,\"limitations\":[\"single task does not prove generality\"]}}],\"result\":{\"decision\":\"task-specific actual answer\"}}" src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.research.search_workspace_detailed","grant_agent.proofs_research_journey.local_workspace_search"],"claim":"A local research query returns its exact Unicode source line and path as evidence; an escaping search scope is refused without changing the source.","id":"p22.research-workspace-search","impact":["Local workspace research evidence and source citations","Research search scope refusal"],"phase":"post"}
