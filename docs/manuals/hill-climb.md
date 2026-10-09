<!-- Generated from manuals/cl/hill-climb.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# hill-climb

## evolver
CL 1
L hill-climb v1 -- Paired evolution with locked judges and fresh confirmation
T t1{ok:true domains:json:"{\"type\":\"array\"}" publicPromotion:false ..}
T t2 json:"{\"type\":\"object\"}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"manual_compression\",\"cl_skill\",\"manual_compression_v2\",\"cl_skill_v2\",\"cl_skill_v3\",\"paul_intent\",\"manual_json_local_v1\"]}"
T t4 str ~"^[a-f0-9]{64}$"
S hill-climb.current:t1=neyvia.evolver.state()
A neyvia.evolver.state(domain?:str) -> t2 -- Read actual receipts; no public release changes
C neyvia.evolver.state observed:neyvia.evolver.state() .publicPromotion == false
A neyvia.evolver.lineage(domain:str) -> t2 -- Read actual receipts; no public release changes
F verify-evolver-lineage "No authored observer check is bound to neyvia.evolver.lineage" -> ask operator blocks:neyvia.evolver.lineage
A neyvia.evolver.receipt(domain:str trial:1..) -> t2 -- Read actual receipts; no public release changes
F verify-evolver-receipt "No authored observer check is bound to neyvia.evolver.receipt" -> ask operator blocks:neyvia.evolver.receipt
A neyvia.evolver.run(domain:t3 requestId:str#1.. maxTrials?:1..2) -> t2 ! -- Start a bounded named frozen domain; local compression uses no model; the other domains use GPT-6 Luna
F verify-evolver-run "No authored observer check is bound to neyvia.evolver.run" -> ask operator blocks:neyvia.evolver.run
A neyvia.evolver.job(requestId:str#1..) -> t2 -- Read actual receipts; no public release changes
F verify-evolver-job "No authored observer check is bound to neyvia.evolver.job" -> ask operator blocks:neyvia.evolver.job
A neyvia.evolver.genome(domain:str genome:t4) -> t2 -- Read actual receipts; no public release changes
F verify-evolver-genome "No authored observer check is bound to neyvia.evolver.genome" -> ask operator blocks:neyvia.evolver.genome
C neyvia.evolver.state observed:neyvia.evolver.state() .publicPromotion == false
P inspect():state=neyvia.evolver.state() C observed -- Inspect frozen evolution without publication
V P inspect -> script why:"typed manual runner; stops at every judgement"
J promotion inspect-receipt|retain-incumbent:"Did discovery and fresh reconfirmation both satisfy the same frozen promotion contract?" -- A Pareto member alone is insufficient. Read paired intervals, corrected alpha, hard gates and distinct panel IDs. Promotion changes only this workspace incumbent.
V J promotion -> human:operator why:"explicit choice required"
X Model sampling is called reproducibly seeded -> CLI has no sampling-seed control. Seeds control task inputs and pair order; provider sampling remains uncontrolled.
X Token count called native Luna token count -> Denominator uses o200k_base reference tokenization; actual CLI input/output usage is recorded separately.
X CL source checks called visual quality -> This first domain measures frozen adherence plus compilation/markup correctness. Browser appearance is outside that measurement.
F Claude owns the Hill climbing screen and rendered lineage journey
F Field L5, other domains and unrestricted rewrite languages require separate adapters and evidence
M hill-climb "Domain source: src/grant_agent/evolver_domains.py; engine: src/grant_agent/evolver_core.py; real runner: scripts/run_t13_evolution.py" src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Repair attempts never exceed the existing hard cap; repair/verify phase counts equal attempts actually used and verification occurs only after passed repair actions.","id":"proofs-e-wz.repair-bounds","impact":["bounded detect-repair-verify loop"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Completion requires a real passed detection or verification phase; proof booleans match executed phase results, tracked changes match before/after hashes and the saved receipt exactly equals the returned receipt.","id":"proofs-e-wz.repair-receipt","impact":["repair evidence","tracked bytes","job completion"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"An invalid repair contract returns a blocked durable receipt with its contract error and runs no command phases or claimed final verification.","id":"proofs-e-wz.repair-blocked","impact":["invalid execution contracts","failure reporting"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.worker.run_local_worker_once","grant_agent.proofs_e_wz.check_worker_repair","grant_agent.proofs_e_wz.self_check"],"claim":"After actual local worker execution, the persisted job status matches its result, all reported phase events are recorded and the repair receipt is registered as a durable artifact.","id":"proofs-e-wz.worker-repair","impact":["cluster worker","repair artifacts","event history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.suite_report.build_suite_summary -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Suite averages, pass rate and preset count exactly reflect supplied observed rows, including the empty suite.","id":"sv.suite.summary","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.suite_report.write_suite_artifacts -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Successful suite artifact writing returns paths whose JSON preserves all input evidence and whose human report lists every preset.","id":"sv.suite.artifacts","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}

## method
CL 1
L hill-climb v1 -- Executable hill-climb method: chronological mechanism and measured quality
T t1 json:"{\"type\":\"object\",\"properties\":{\"accepted\":{\"type\":\"boolean\"},\"adherence\":{\"type\":\"number\"},\"fitness\":{\"type\":[\"number\",\"null\"]},\"errors\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"accepted\",\"adherence\",\"fitness\",\"errors\"],\"additionalProperties\":true}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"hill-climb\",\"creativity\",\"critique-review\",\"efficiency\",\"research\",\"design\"]}"
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"object\",\"additionalProperties\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\",\"minLength\":1},\"sha256\":{\"type\":\"string\",\"pattern\":\"^[a-f0-9]{64}$\"}},\"required\":[\"path\",\"sha256\"],\"additionalProperties\":false}}"
T t5 json:"{\"type\":\"number\",\"minimum\":0,\"maximum\":1}"
S hill-climb.adherence:t1=neyvia.workflow.check(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens)
A neyvia.workflow.check(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 -- Validate ordered workflow evidence
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
A neyvia.workflow.record(manual:t2 report:t3 evidence:t4 outcomeQuality:t5 tokens:0..) -> t1 ! -- Persist a validated workflow receipt under the selected task root
C neyvia.workflow.record adhered:neyvia.workflow.check(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
C neyvia.workflow.check adhered:neyvia.workflow.check(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens) .accepted == true
P verify-and-record(report:t3 evidence:t4 outcomeQuality:t5 tokens:0..):verified=neyvia.workflow.check(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered; recorded=neyvia.workflow.record(evidence:evidence manual:"hill-climb" outcomeQuality:outcomeQuality report:report tokens:tokens) C adhered -- Verify defining workflow mechanism against host evidence and persist the acceptance receipt
V P verify-and-record -> script why:"typed manual runner; stops at every judgement"
J quality accept|revise:"Does the outcome satisfy the actual task, beyond recorded adherence?" -- Use an independent frozen host quality judge; self-reported quality is not evidence.
V J quality -> human:operator why:"explicit choice required"
X A model writes its own successful receipt, outcome score or token count -> The host supplies hash-bound local evidence files, independently judged quality and provider usage; invented IDs fail
F Executable adherence is necessary but not sufficient for semantic quality. Outcome quality belongs to a separate frozen task judge.
F Three paired tasks provide bounded evidence and cannot authorize statistical Evolver promotion.
M hill-climb "Baseline first, before changing anything. Freeze the executable check, candidate task data and noise threshold." src:"authored manual" state:verified
M hill-climb "Change exactly one mechanism; measure the candidate with the same checkHash as baseline. Higher value means better; transform minimization metrics before judging." src:"authored manual" state:verified
M hill-climb "Accept only measured value > baseline value + frozen noise. A tie or inconclusive run keeps the baseline. Link measurement to a real research-ledger receipt and state a stop rule." src:"authored manual" state:verified
M hill-climb "Report shape: {events:[{stage,data}],result:object}. Required chronological stages: baseline, change, measure, decision, log, stop" src:"authored manual" state:verified
M hill-climb "baseline{receipt}; change{candidate,changes:[one mechanism]}; measure{receipt}; decision{keep:boolean,reason}; log{receipt}; stop{rule}. Evidence measurement receipts have checkHash,value,noise; ledger receipt has kind=research-ledger,measurement=measure receipt ID." src:"authored manual" state:verified
M hill-climb "Public tool evidence is {ID:{path:task-root-relative receipt JSON,sha256:receipt SHA256}}. Pure host evaluator evidence maps IDs to loaded measurements. Public tool outcome quality is explicitly caller-scored, never automatically verified." src:"authored manual" state:verified
M hill-climb "Every data.receipt is a STRING naming a key in the host evidence mapping: for example {\"receipt\":\"measurement\"}. Never copy the receipt object or create a new ID. Public tool callers pass path/SHA descriptors separately; event receipt fields remain string IDs. Use the exact keys the current task supplied, not the example keys below." src:"authored manual" state:verified
M hill-climb "Conforming shape example (replace illustrative values, IDs and decision with the actual task/evidence; do not copy its outcome): {\"events\":[{\"stage\":\"baseline\",\"data\":{\"receipt\":\"baseline\"}},{\"stage\":\"change\",\"data\":{\"candidate\":\"one candidate name\",\"changes\":[\"one mechanism change\"]}},{\"stage\":\"measure\",\"data\":{\"receipt\":\"measurement\"}},{\"stage\":\"decision\",\"data\":{\"keep\":false,\"reason\":\"measurement does not beat baseline beyond noise\"}},{\"stage\":\"log\",\"data\":{\"receipt\":\"log\"}},{\"stage\":\"stop\",\"data\":{\"rule\":\"stop after this measured decision\"}}],\"result\":{\"decision\":\"task-specific actual answer\"}}" src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Repair attempts never exceed the existing hard cap; repair/verify phase counts equal attempts actually used and verification occurs only after passed repair actions.","id":"proofs-e-wz.repair-bounds","impact":["bounded detect-repair-verify loop"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Completion requires a real passed detection or verification phase; proof booleans match executed phase results, tracked changes match before/after hashes and the saved receipt exactly equals the returned receipt.","id":"proofs-e-wz.repair-receipt","impact":["repair evidence","tracked bytes","job completion"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"An invalid repair contract returns a blocked durable receipt with its contract error and runs no command phases or claimed final verification.","id":"proofs-e-wz.repair-blocked","impact":["invalid execution contracts","failure reporting"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.worker.run_local_worker_once","grant_agent.proofs_e_wz.check_worker_repair","grant_agent.proofs_e_wz.self_check"],"claim":"After actual local worker execution, the persisted job status matches its result, all reported phase events are recorded and the repair receipt is registered as a durable artifact.","id":"proofs-e-wz.worker-repair","impact":["cluster worker","repair artifacts","event history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.suite_report.build_suite_summary -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Suite averages, pass rate and preset count exactly reflect supplied observed rows, including the empty suite.","id":"sv.suite.summary","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.suite_report.write_suite_artifacts -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Successful suite artifact writing returns paths whose JSON preserves all input evidence and whose human report lists every preset.","id":"sv.suite.artifacts","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}

## overview
CL 1
L hill-climb v1 -- Frozen improvement receipts, history and measured Pareto tradeoffs
T t1{records:json:"{\"type\":\"array\"}" competitions:json:"{\"type\":\"array\"}" automaticTraining:false automaticPromotion:false ..}
S hill-climb.current:t1=neyvia.lab.state()
A neyvia.lab.state() -> t1 -- Read latest 50 records and eligible measured Pareto sets; automaticTraining/Promotion and semanticQualityVerified remain false
C neyvia.lab.state no-promotion:neyvia.lab.state() .automaticPromotion == false
C neyvia.lab.state no-promotion:neyvia.lab.state() .automaticPromotion == false
P inspect-measurements():lab=neyvia.lab.state() C no-promotion; J candidate -- Read frozen improvement receipts and decide whether comparisons support the requested objective
V P inspect-measurements -> script why:"typed manual runner; stops at every judgement"
J candidate compare|more-evidence:"Do these eligible candidates answer the improvement objective?" -- Compare same definitionHash, boundary and instrument key set. Pareto minimizes numeric values/meanMs/bytes; a frontier candidate is not a semantic winner. Reject invalid/nonfinite measurements; missing instruments prevent domination claims.
V J candidate -> human:operator why:"explicit choice required"
X Pareto winner is called model promotion -> Read automaticPromotion=false and semanticQualityVerified=false; perform separate matched behavioral evaluation
X Candidates have different instrument key sets -> Do not claim domination across incomparable vectors
X Records lack finite numeric measurements or eligibility -> Exclude invalid vectors; collect missing evidence before comparison
F Legacy Lab measurements remain separate from frozen domain-specific Evolver evaluations
F Legacy competitions do not train or promote models
M hill-climb "Source: src/grant_agent/neyvia_lab_board.py (vector, pareto, state); tests/test_neyvia_native_studios.py." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Repair attempts never exceed the existing hard cap; repair/verify phase counts equal attempts actually used and verification occurs only after passed repair actions.","id":"proofs-e-wz.repair-bounds","impact":["bounded detect-repair-verify loop"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Completion requires a real passed detection or verification phase; proof booleans match executed phase results, tracked changes match before/after hashes and the saved receipt exactly equals the returned receipt.","id":"proofs-e-wz.repair-receipt","impact":["repair evidence","tracked bytes","job completion"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"An invalid repair contract returns a blocked durable receipt with its contract error and runs no command phases or claimed final verification.","id":"proofs-e-wz.repair-blocked","impact":["invalid execution contracts","failure reporting"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.worker.run_local_worker_once","grant_agent.proofs_e_wz.check_worker_repair","grant_agent.proofs_e_wz.self_check"],"claim":"After actual local worker execution, the persisted job status matches its result, all reported phase events are recorded and the repair receipt is registered as a durable artifact.","id":"proofs-e-wz.worker-repair","impact":["cluster worker","repair artifacts","event history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.suite_report.build_suite_summary -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Suite averages, pass rate and preset count exactly reflect supplied observed rows, including the empty suite.","id":"sv.suite.summary","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.suite_report.write_suite_artifacts -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Successful suite artifact writing returns paths whose JSON preserves all input evidence and whose human report lists every preset.","id":"sv.suite.artifacts","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}

## proofs-e-sv
CL 1
L hill-climb v1 -- PROOFS-e s-v host contracts and confined startup receipts
X A passed scratch validator or receipt reducer is mistaken for provider, native release, NAS or rendered UI proof -> Read the adapter boundary and retain every unmapped case in the migration frontier
F config/proofs/proofs-e-sv.json lists exact retained cases and the missing host/journey receipt; pending cases are never deletion authority.
M hill-climb "Production calls enforce these semantic contracts before returning. Startup entry: grant_agent.proofs_e_sv.self_check with a fresh confined root." src:"authored manual" state:verified
M hill-climb "Run the registered proofs-e-sv area through neyvia.verify to obtain real scratch process, file, archive, language-compiler and local HTTP receipts." src:"authored manual" state:verified
M hill-climb "This chapter is separate from other area additions; sv.* contract IDs identify its host-owned guarantees." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Repair attempts never exceed the existing hard cap; repair/verify phase counts equal attempts actually used and verification occurs only after passed repair actions.","id":"proofs-e-wz.repair-bounds","impact":["bounded detect-repair-verify loop"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Completion requires a real passed detection or verification phase; proof booleans match executed phase results, tracked changes match before/after hashes and the saved receipt exactly equals the returned receipt.","id":"proofs-e-wz.repair-receipt","impact":["repair evidence","tracked bytes","job completion"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"An invalid repair contract returns a blocked durable receipt with its contract error and runs no command phases or claimed final verification.","id":"proofs-e-wz.repair-blocked","impact":["invalid execution contracts","failure reporting"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.worker.run_local_worker_once","grant_agent.proofs_e_wz.check_worker_repair","grant_agent.proofs_e_wz.self_check"],"claim":"After actual local worker execution, the persisted job status matches its result, all reported phase events are recorded and the repair receipt is registered as a durable artifact.","id":"proofs-e-wz.worker-repair","impact":["cluster worker","repair artifacts","event history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.suite_report.build_suite_summary -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Suite averages, pass rate and preset count exactly reflect supplied observed rows, including the empty suite.","id":"sv.suite.summary","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.suite_report.write_suite_artifacts -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Successful suite artifact writing returns paths whose JSON preserves all input evidence and whose human report lists every preset.","id":"sv.suite.artifacts","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}

## proofs-e-wz
CL 1
L hill-climb v1 -- PROOFS-e W-Z: live contracts and scratch self-checks
X A local fixture is mistaken for a real provider, signed desktop release or whole-suite replacement -> Read the source-bound receipt, per-case coverage map and unresolved frontier before retirement or promotion
F Backend suite and paired-desktop controller scenarios remain pending unless every original predicate has a real action site and observed scratch procedure.
F Hidden-process AST scanner self-tests protect test-only tooling and are retained pending lead retirement review; no source-text scan is relabeled as production proof.
F Legacy desktop-ui/fluxioHelpers.js is absent; its workspace-selection tests remain pending impact/history review.
F The original bootstrap test expected newest merged turn first; its coverage row explicitly supersedes that stale assertion with observed chronological ordering, preserving all other bootstrap/lazy-detail predicates.
M hill-climb "Self-check entry: grant_agent.proofs_e_wz.self_check; CLI: neyvia verify --root <workspace> --area proofs-e-wz" src:"authored manual" state:verified
M hill-climb "Manifest: config/proofs/proofs-e-wz.json; host sites enforce these contracts on every corresponding real action." src:"authored manual" state:verified
M hill-climb "Fixtures use disposable SQLite stores, real owned Python child commands, localhost HTTP port 48503 and bounded source transport injection." src:"authored manual" state:verified
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Repair attempts never exceed the existing hard cap; repair/verify phase counts equal attempts actually used and verification occurs only after passed repair actions.","id":"proofs-e-wz.repair-bounds","impact":["bounded detect-repair-verify loop"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"Completion requires a real passed detection or verification phase; proof booleans match executed phase results, tracked changes match before/after hashes and the saved receipt exactly equals the returned receipt.","id":"proofs-e-wz.repair-receipt","impact":["repair evidence","tracked bytes","job completion"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.self_repair.execute_self_repair_job","grant_agent.proofs_e_wz.check_repair","grant_agent.proofs_e_wz.self_check"],"claim":"An invalid repair contract returns a blocked durable receipt with its contract error and runs no command phases or claimed final verification.","id":"proofs-e-wz.repair-blocked","impact":["invalid execution contracts","failure reporting"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.worker.run_local_worker_once","grant_agent.proofs_e_wz.check_worker_repair","grant_agent.proofs_e_wz.self_check"],"claim":"After actual local worker execution, the persisted job status matches its result, all reported phase events are recorded and the repair receipt is registered as a durable artifact.","id":"proofs-e-wz.worker-repair","impact":["cluster worker","repair artifacts","event history"],"phase":"post"}
-- @proof {"checkedAt":["grant_agent.suite_report.build_suite_summary -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Suite averages, pass rate and preset count exactly reflect supplied observed rows, including the empty suite.","id":"sv.suite.summary","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
-- @proof {"checkedAt":["grant_agent.suite_report.write_suite_artifacts -> grant_agent.proofs_e_sv.check","grant_agent.proofs_e_sv.self_check"],"claim":"Successful suite artifact writing returns paths whose JSON preserves all input evidence and whose human report lists every preset.","id":"sv.suite.artifacts","impact":["hill-climb","PROOFS-e s-v behavior"],"phase":"invariant"}
