<!-- Generated from manuals/cl/local-evaluations.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-evaluations

## evaluation
CL 1
L local-evaluations v1 -- Evidence-backed task reasoning and local evaluation
T t1{question_id:str answer:str#..4000 checks:json:"{\"type\":\"array\",\"minItems\":1,\"maxItems\":12,\"uniqueItems\":true,\"items\":{\"type\":\"string\"},\"description\":\"IDs of already saved artifact obligations; do not invent check results.\"}" expected_revision:0..}
T t2 json:"{\"type\":\"object\"}"
T t3{question:str#1..1200 decision:str#1..1200}
T t4{understanding:str#1..6000 expected_revision:json:"{\"type\":\"integer\",\"minimum\":0,\"description\":\"Current brief.revision, or 0 before first save. The top-level revision belongs to preferences.\"}" assumptions?:[str#..1000]#..12 directions?:json:"{\"type\":\"array\",\"maxItems\":4,\"items\":{\"type\":\"object\",\"additionalProperties\":false,\"properties\":{\"id\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120},\"title\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120},\"approach\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":1500},\"tradeoff\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":1500}},\"required\":[\"id\",\"title\",\"approach\",\"tradeoff\"]},\"description\":\"Omit to preserve the saved choices. Selected direction content must remain unchanged.\"}" open_questions?:[str#..1000]#..12}
T t5 json:"{\"type\":\"array\"}"
A intelligence.answer_self(workId:str arguments:t1) -> t2 ! -- Record your answer against existing artifact obligation IDs, checking their current evidence. Failed or stale checks keep the question unresolved. Use its exact expected_revision. Arguments: question_id, answer, checks, expected_revision.
F verify-intelligence-answer_self "No authored observer check is bound to intelligence.answer_self" -> ask operator blocks:intelligence.answer_self
A intelligence.ask_self(workId:str arguments:t3) -> t2 ! -- Record a concrete unresolved question and the decision it changes. This does not call another model or request user input. Arguments: question, decision.
F verify-intelligence-ask_self "No authored observer check is bound to intelligence.ask_self" -> ask operator blocks:intelligence.ask_self
A intelligence.brief(workId:str arguments:t4) -> t2 ! -- Save or revise the task brief. Use expected_revision from intelligence.collaboration.brief.revision (0 when no brief), not the preferences revision. Omitted lists retain their saved values; user corrections and the selected direction are protected. Arguments: understanding.
F verify-intelligence-brief "No authored observer check is bound to intelligence.brief" -> ask operator blocks:intelligence.brief
A intelligence.handoff(workId:str arguments:t2) -> t2 ! -- Persist an immutable handoff with objective, protected decision IDs, answer key and artifact identities. Arguments: objective, protected_decisions, answers.
F verify-intelligence-handoff "No authored observer check is bound to intelligence.handoff" -> ask operator blocks:intelligence.handoff
A intelligence.obligate(workId:str arguments:t2) -> t2 ! -- Attach a runnable file_contains or json_path criterion to a real artifact hash. Arguments: artifact, sha256, criterion.
F verify-intelligence-obligate "No authored observer check is bound to intelligence.obligate" -> ask operator blocks:intelligence.obligate
A intelligence.rationale(workId:str arguments:t2) -> t2 ! -- Save a versioned purpose and protected decisions for an element. Arguments: element_id, purpose.
F verify-intelligence-rationale "No authored observer check is bound to intelligence.rationale" -> ask operator blocks:intelligence.rationale
A lab.causal(baseline:str variant:str factor:str workId:str) -> t2 ! -- Compare reported trials only when one declared factor changes; expose confounded comparisons
F verify-lab-causal "No authored observer check is bound to lab.causal" -> ask operator blocks:lab.causal
A lab.curriculum(identity:str examples:t5) -> t2 ! -- Freeze training and holdout evidence; reject duplicate content and task-family leakage
F verify-lab-curriculum "No authored observer check is bound to lab.curriculum" -> ask operator blocks:lab.curriculum
A lab.journey(path:str) -> t2 ! -- Analyze a timestamped interaction trace for delay, unanswered actions, errors and continuity events
F verify-lab-journey "No authored observer check is bound to lab.journey" -> ask operator blocks:lab.journey
A lab.rehearse(experiment_id:str script:str workId:str) -> t2 ! -- Run an existing snapshot script with installed software in a managed session; host access remains
F verify-lab-rehearse "No authored observer check is bound to lab.rehearse" -> ask operator blocks:lab.rehearse
A lab.resolve_uncertainty(identity:str assumption:int instrument:str target:str) -> t2 ! -- Attach a real frozen-instrument measurement to an assumption without promoting its semantic claim
F verify-lab-resolve_uncertainty "No authored observer check is bound to lab.resolve_uncertainty" -> ask operator blocks:lab.resolve_uncertainty
A lab.uncertainty(identity:str assumptions:t5) -> t2 ! -- Rank explicit assumptions by estimated impact and uncertainty per experiment cost
F verify-lab-uncertainty "No authored observer check is bound to lab.uncertainty" -> ask operator blocks:lab.uncertainty
A lab.visual_guard(baseline:str candidate:str regions:t5) -> t2 ! -- Compare actual protected image pixels, including alpha, without changing either image
F verify-lab-visual_guard "No authored observer check is bound to lab.visual_guard" -> ask operator blocks:lab.visual_guard
P verify-intelligence-answer_self(workId:str arguments:t1):saved=intelligence.answer_self(arguments:arguments workId:workId) -- Record your answer against existing artifact obligation IDs, checking their current evidence. Failed or stale checks keep the question unresolved. Use its exact expected_revision. Arguments: question_id, answer, checks, expected_revision.
V P verify-intelligence-answer_self -> script why:"typed manual runner; stops at every judgement"
P verify-intelligence-ask_self(workId:str arguments:t3):saved=intelligence.ask_self(arguments:arguments workId:workId) -- Record a concrete unresolved question and the decision it changes. This does not call another model or request user input. Arguments: question, decision.
V P verify-intelligence-ask_self -> script why:"typed manual runner; stops at every judgement"
P verify-intelligence-brief(workId:str arguments:t4):saved=intelligence.brief(arguments:arguments workId:workId) -- Save or revise the task brief. Use expected_revision from intelligence.collaboration.brief.revision (0 when no brief), not the preferences revision. Omitted lists retain their saved values; user corrections and the selected direction are protected. Arguments: understanding.
V P verify-intelligence-brief -> script why:"typed manual runner; stops at every judgement"
P verify-intelligence-handoff(workId:str arguments:t2):saved=intelligence.handoff(arguments:arguments workId:workId) -- Persist an immutable handoff with objective, protected decision IDs, answer key and artifact identities. Arguments: objective, protected_decisions, answers.
V P verify-intelligence-handoff -> script why:"typed manual runner; stops at every judgement"
P verify-intelligence-obligate(workId:str arguments:t2):saved=intelligence.obligate(arguments:arguments workId:workId) -- Attach a runnable file_contains or json_path criterion to a real artifact hash. Arguments: artifact, sha256, criterion.
V P verify-intelligence-obligate -> script why:"typed manual runner; stops at every judgement"
P verify-intelligence-rationale(workId:str arguments:t2):saved=intelligence.rationale(arguments:arguments workId:workId) -- Save a versioned purpose and protected decisions for an element. Arguments: element_id, purpose.
V P verify-intelligence-rationale -> script why:"typed manual runner; stops at every judgement"
P verify-lab-causal(baseline:str variant:str factor:str workId:str):saved=lab.causal(baseline:baseline factor:factor variant:variant workId:workId) -- Compare reported trials only when one declared factor changes; expose confounded comparisons
V P verify-lab-causal -> script why:"typed manual runner; stops at every judgement"
P verify-lab-curriculum(identity:str examples:t5):saved=lab.curriculum(examples:examples identity:identity) -- Freeze training and holdout evidence; reject duplicate content and task-family leakage
V P verify-lab-curriculum -> script why:"typed manual runner; stops at every judgement"
P verify-lab-journey(path:str):saved=lab.journey(path:path) -- Analyze a timestamped interaction trace for delay, unanswered actions, errors and continuity events
V P verify-lab-journey -> script why:"typed manual runner; stops at every judgement"
P verify-lab-rehearse(experiment_id:str script:str workId:str):saved=lab.rehearse(experiment_id:experiment_id script:script workId:workId) -- Run an existing snapshot script with installed software in a managed session; host access remains
V P verify-lab-rehearse -> script why:"typed manual runner; stops at every judgement"
P verify-lab-resolve_uncertainty(identity:str assumption:int instrument:str target:str):saved=lab.resolve_uncertainty(assumption:assumption identity:identity instrument:instrument target:target) -- Attach a real frozen-instrument measurement to an assumption without promoting its semantic claim
V P verify-lab-resolve_uncertainty -> script why:"typed manual runner; stops at every judgement"
P verify-lab-uncertainty(identity:str assumptions:t5):saved=lab.uncertainty(assumptions:assumptions identity:identity) -- Rank explicit assumptions by estimated impact and uncertainty per experiment cost
V P verify-lab-uncertainty -> script why:"typed manual runner; stops at every judgement"
P verify-lab-visual_guard(baseline:str candidate:str regions:t5):saved=lab.visual_guard(baseline:baseline candidate:candidate regions:regions) -- Compare actual protected image pixels, including alpha, without changing either image
V P verify-lab-visual_guard -> script why:"typed manual runner; stops at every judgement"
X A reported answer, trial or trace is presented as independent model quality proof -> Keep its declared provenance and prove the actual artifact criterion separately.
X A saved witness becomes stale after artifact changes -> Re-read current bytes and definitions; completion is refused until the evidence is restored.
F Semantic correctness of reported answers, trials and traces needs a separate evaluator.
F Model training and promotion require separate real evaluation and authorization.
M local-evaluations "Use saved obligation IDs and the current question or brief revision." src:"authored manual" state:verified
M local-evaluations "Frozen curricula exclude holdout bytes from lesson packets and reject cross-split family leakage." src:"authored manual" state:verified
M local-evaluations "Rehearsal runs an existing scoped snapshot script and requires an actual successful managed process." src:"authored manual" state:verified
