<!-- Generated from manuals/cl/critique-review.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# critique-review

## workflow
CL 1
L critique-review v1 -- Executable critique-review method: chronological mechanism and measured quality
T t1 json:"{\"type\":\"object\",\"properties\":{\"accepted\":{\"type\":\"boolean\"},\"adherence\":{\"type\":\"number\"},\"fitness\":{\"type\":[\"number\",\"null\"]},\"errors\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"accepted\",\"adherence\",\"fitness\",\"errors\"],\"additionalProperties\":true}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"hill-climb\",\"creativity\",\"critique-review\",\"efficiency\",\"research\",\"design\"]}"
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"object\",\"additionalProperties\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\",\"minLength\":1},\"sha256\":{\"type\":\"string\",\"pattern\":\"^[a-f0-9]{64}$\"}},\"required\":[\"path\",\"sha256\"],\"additionalProperties\":false}}"
T t5 json:"{\"type\":\"number\",\"minimum\":0,\"maximum\":1}"
S critique-review.adherence:t1=neyvia.workflow.check(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens)
A neyvia.workflow.check(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 -- Validate ordered workflow evidence
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
A neyvia.workflow.record(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 ! -- Persist a validated workflow receipt under the selected task root
C neyvia.workflow.record adhered:neyvia.workflow.check(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
P verify-and-record(report:t3 evidence:t4 outcomeQuality:t5 tokens:0..):verified=neyvia.workflow.check(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered; recorded=neyvia.workflow.record(evidence:evidence manual:"critique-review" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered -- Verify defining workflow mechanism against host evidence and persist the acceptance receipt
V P verify-and-record -> script why:"typed manual runner; stops at every judgement"
J quality accept|revise:"Does the outcome satisfy the actual task, beyond recorded adherence?" -- Use an independent frozen host quality judge; self-reported quality is not evidence.
V J quality -> model:large evidence:artifact why:"model judgment bound to current evidence"
X A model writes its own successful receipt, outcome score or token count -> The host supplies hash-bound local evidence files, independently judged quality and provider usage; invented IDs fail
F Executable adherence is necessary but not sufficient for semantic quality. Outcome quality belongs to a separate frozen task judge.
F Three paired tasks provide bounded evidence and cannot authorize statistical Evolver promotion.
M critique-review "Compare the delivered result with the plan defining mechanism, rather than the name or appearance of a feature." src:"authored manual" state:verified
M critique-review "Attack your own result: record at least two failure paths and the evidence behind each; identify what was not shown." src:"authored manual" state:verified
M critique-review "Verification references actual host receipts. Do not claim done while a required mechanism remains missing or any linked receipt failed." src:"authored manual" state:verified
M critique-review "Report shape: {events:[{stage,data}],result:object}. Required chronological stages: plan, attack, verify, decision" src:"authored manual" state:verified
M critique-review "plan{mechanism}; attack{risks:[{failure,evidence}]>=2}; verify{receipts:[host receipt IDs]}; decision{done:boolean,missing:[strings]}. Verification receipts have success:boolean." src:"authored manual" state:verified
M critique-review "Public tool evidence is {ID:{path:task-root-relative receipt JSON,sha256:receipt SHA256}}. Pure host evaluator evidence maps IDs to loaded measurements. Public tool outcome quality is explicitly caller-scored, never automatically verified." src:"authored manual" state:verified
M critique-review "Every data.receipt is a STRING naming a key in the host evidence mapping: for example {\"receipt\":\"measurement\"}. Never copy the receipt object or create a new ID. Public tool callers pass path/SHA descriptors separately; event receipt fields remain string IDs. Use the exact keys the current task supplied, not the example keys below." src:"authored manual" state:verified
M critique-review "Conforming shape example (replace illustrative values, IDs and decision with the actual task/evidence; do not copy its outcome): {\"events\":[{\"stage\":\"plan\",\"data\":{\"mechanism\":\"observable full task completion\"}},{\"stage\":\"attack\",\"data\":{\"risks\":[{\"failure\":\"main output lacks required wiring\",\"evidence\":\"observed source path missing\"},{\"failure\":\"failure case lacks recovery\",\"evidence\":\"captured failed journey\"}]}},{\"stage\":\"verify\",\"data\":{\"receipts\":[\"verification\"]}},{\"stage\":\"decision\",\"data\":{\"done\":false,\"missing\":[\"required wiring absent\"]}}],\"result\":{\"decision\":\"task-specific actual answer\"}}" src:"authored manual" state:verified
