<!-- Generated from manuals/cl/creativity.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# creativity

## workflow
CL 1
L creativity v1 -- Executable creativity method: chronological mechanism and measured quality
T t1 json:"{\"type\":\"object\",\"properties\":{\"accepted\":{\"type\":\"boolean\"},\"adherence\":{\"type\":\"number\"},\"fitness\":{\"type\":[\"number\",\"null\"]},\"errors\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"accepted\",\"adherence\",\"fitness\",\"errors\"],\"additionalProperties\":true}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"hill-climb\",\"creativity\",\"critique-review\",\"efficiency\",\"research\",\"design\"]}"
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"object\",\"additionalProperties\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\",\"minLength\":1},\"sha256\":{\"type\":\"string\",\"pattern\":\"^[a-f0-9]{64}$\"}},\"required\":[\"path\",\"sha256\"],\"additionalProperties\":false}}"
T t5 json:"{\"type\":\"number\",\"minimum\":0,\"maximum\":1}"
S creativity.adherence:t1=neyvia.workflow.check(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens)
A neyvia.workflow.check(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 -- Validate ordered workflow evidence
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
A neyvia.workflow.record(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 ! -- Persist a validated workflow receipt under the selected task root
C neyvia.workflow.record adhered:neyvia.workflow.check(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
P verify-and-record(report:t3 evidence:t4 outcomeQuality:t5 tokens:0..):verified=neyvia.workflow.check(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered; recorded=neyvia.workflow.record(evidence:evidence manual:"creativity" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered -- Verify defining workflow mechanism against host evidence and persist the acceptance receipt
V P verify-and-record -> script why:"typed manual runner; stops at every judgement"
J quality accept|revise:"Does the outcome satisfy the actual task, beyond recorded adherence?" -- Use an independent frozen host quality judge; self-reported quality is not evidence.
V J quality -> model:large evidence:artifact why:"model judgment bound to current evidence"
X A model writes its own successful receipt, outcome score or token count -> The host supplies hash-bound local evidence files, independently judged quality and provider usage; invented IDs fail
F Executable adherence is necessary but not sufficient for semantic quality. Outcome quality belongs to a separate frozen task judge.
F Three paired tasks provide bounded evidence and cannot authorize statistical Evolver promotion.
M creativity "Diverge before converging: reframe the question, borrow a mechanism from another field and flip one constraint." src:"authored manual" state:verified
M creativity "Record at least three genuinely different causal mechanisms, each with family, benefit and finite nonnegative cost. Paraphrases do not count; the independent host quality judge evaluates semantic diversity." src:"authored manual" state:verified
M creativity "Before choice, record positive weights for novelty, usefulness and cost. Explain the choice against these criteria and expose the rejected tradeoffs." src:"authored manual" state:verified
M creativity "Report shape: {events:[{stage,data}],result:object}. Required chronological stages: reframe, diverge, criteria, choose" src:"authored manual" state:verified
M creativity "reframe{question,borrowedField,constraintFlip}; diverge{options:[{id,family,mechanism,benefit,cost}]>=3}; criteria{weights:{novelty,usefulness,cost}>0}; choose{option,reason}. Families must name different causal approaches, not cosmetic names." src:"authored manual" state:verified
M creativity "Public tool evidence is {ID:{path:task-root-relative receipt JSON,sha256:receipt SHA256}}. Pure host evaluator evidence maps IDs to loaded measurements. Public tool outcome quality is explicitly caller-scored, never automatically verified." src:"authored manual" state:verified
M creativity "Every data.receipt is a STRING naming a key in the host evidence mapping: for example {\"receipt\":\"measurement\"}. Never copy the receipt object or create a new ID. Public tool callers pass path/SHA descriptors separately; event receipt fields remain string IDs. Use the exact keys the current task supplied, not the example keys below." src:"authored manual" state:verified
M creativity "Conforming shape example (replace illustrative values, IDs and decision with the actual task/evidence; do not copy its outcome): {\"events\":[{\"stage\":\"reframe\",\"data\":{\"question\":\"reframed useful question\",\"borrowedField\":\"control theory\",\"constraintFlip\":\"remove the costly resource\"}},{\"stage\":\"diverge\",\"data\":{\"options\":[{\"id\":\"first\",\"family\":\"deterministic replay\",\"mechanism\":\"reuse a verified computation\",\"benefit\":\"lower latency\",\"cost\":1},{\"id\":\"second\",\"family\":\"adaptive scheduling\",\"mechanism\":\"change when work happens\",\"benefit\":\"less contention\",\"cost\":2},{\"id\":\"third\",\"family\":\"human guided retrieval\",\"mechanism\":\"ask for relevant prior examples\",\"benefit\":\"better task fit\",\"cost\":3}]}},{\"stage\":\"criteria\",\"data\":{\"weights\":{\"novelty\":1,\"usefulness\":3,\"cost\":2}}},{\"stage\":\"choose\",\"data\":{\"option\":\"first\",\"reason\":\"best usefulness per cost under the constraint\"}}],\"result\":{\"decision\":\"task-specific actual answer\"}}" src:"authored manual" state:verified
