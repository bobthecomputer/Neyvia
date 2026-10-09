<!-- Generated from manuals/cl/local-records.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-records

## records
CL 1
L local-records v1 -- Exact local records and declared artifact criteria
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"baseline\",\"variant\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\"user\",\"provisional\",\"undecided\"]}"
T t4 json:"{\"type\":\"array\"}"
T t5 [str]
T t6 json:"{\"type\":\"string\",\"enum\":[\"input\",\"frame\",\"state\",\"error\",\"timing\"]}"
T t7 json:"{\"type\":\"string\",\"description\":\"Optional screenshot path inside the active workspace. Omit to use the managed artifact path.\"}"
T t8{holdout:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" proposal:json:"{\"type\":\"object\"}"}
T t9{instrument:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" baseline:str#1..4096 candidate:str#1..4096}
T t10{holdout:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" targets:[str#1..4096]#1..20}
T t11{i:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" spec:{instruments:json:"{\"type\":\"array\",\"minItems\":1,\"maxItems\":20,\"uniqueItems\":true,\"items\":{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}}" ..}}
T t12{i:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" spec:{kind:json:"{\"type\":\"string\",\"enum\":[\"json_numeric\",\"image\",\"trace_timing\"]}" key?:str#1..256 max?:num maxMeanMs?:json:"{\"type\":\"number\",\"minimum\":0}" minWidth?:0.. minHeight?:0.. maxBytes?:0..}}
T t13{instrument:json:"{\"type\":\"string\",\"minLength\":1,\"maxLength\":120,\"pattern\":\"^[A-Za-z0-9][A-Za-z0-9_.-]*$\"}" target:str#1..4096}
T t14{context:json:"{\"type\":\"string\",\"enum\":[\"landing-page\",\"product-ui\",\"research\",\"game\"]}" before_path:str#1..4096 after_path:str#1..4096 correction:str#1..12000 agent_id?:str#..120}
A behavior.create(experimentId:str baselineInput:str variantInput:str acceptance:t1 requestedRoute:t1 budget:t1 workId:str) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-behavior-create "No authored observer check is bound to behavior.create" -> ask operator blocks:behavior.create
A behavior.observe(experimentId:str variant:t2 response:str actualRoute:t1 latencyMs?:num cost?:num workId:str) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-behavior-observe "No authored observer check is bound to behavior.observe" -> ask operator blocks:behavior.observe
A experience.compare(workId:str baseline:str candidate:str preference:t3 observations?:t1) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experience-compare "No authored observer check is bound to experience.compare" -> ask operator blocks:experience.compare
A experience.investigate(workId:str hypothesis:str experiment:t1 references?:t4) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experience-investigate "No authored observer check is bound to experience.investigate" -> ask operator blocks:experience.investigate
A experience.note(workId:str lesson:str conditions:str invalidation:str evidence:t5) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experience-note "No authored observer check is bound to experience.note" -> ask operator blocks:experience.note
A experience.trace(workId:str traceId:str eventKind:t6 payload:t1 references?:t4) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experience-trace "No authored observer check is bound to experience.trace" -> ask operator blocks:experience.trace
A experiment.create(experimentId:str source:str launchRecipe?:t1 resetRecipe?:t1) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experiment-create "No authored observer check is bound to experiment.create" -> ask operator blocks:experiment.create
A experiment.restore(experimentId:str restoreId:str) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-experiment-restore "No authored observer check is bound to experiment.restore" -> ask operator blocks:experiment.restore
A orchestration.compile(source:str outputPath?:t7) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-orchestration-compile "No authored observer check is bound to orchestration.compile" -> ask operator blocks:orchestration.compile
A quality.challenge(workId:str arguments:t8) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-challenge "No authored observer check is bound to quality.challenge" -> ask operator blocks:quality.challenge
A quality.compare(workId:str arguments:t9) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-compare "No authored observer check is bound to quality.compare" -> ask operator blocks:quality.compare
A quality.examine(workId:str arguments:t10) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-examine "No authored observer check is bound to quality.examine" -> ask operator blocks:quality.examine
A quality.holdout(workId:str arguments:t11) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-holdout "No authored observer check is bound to quality.holdout" -> ask operator blocks:quality.holdout
A quality.instrument(workId:str arguments:t12) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-instrument "No authored observer check is bound to quality.instrument" -> ask operator blocks:quality.instrument
A quality.measure(workId:str arguments:t13) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-quality-measure "No authored observer check is bound to quality.measure" -> ask operator blocks:quality.measure
A taste.correction(workId:str arguments:t14) -> t1 ! -- Persist an exact proposed record, frozen criterion measurement, compiled plan or isolated byte copy
F verify-taste-correction "No authored observer check is bound to taste.correction" -> ask operator blocks:taste.correction
P record-behavior-create(experimentId:str baselineInput:str variantInput:str acceptance:t1 requestedRoute:t1 budget:t1 workId:str):saved=behavior.create(acceptance:acceptance baselineInput:baselineInput budget:budget experimentId:experimentId requestedRoute:requestedRoute variantInput:variantInput workId:workId) -- Freeze a matched API behavioral experiment, observable criterion, route and call budget; does not run a model.
V P record-behavior-create -> script why:"typed manual runner; stops at every judgement"
P record-behavior-observe(experimentId:str variant:t2 response:str actualRoute:t1 latencyMs:num cost:num workId:str):saved=behavior.observe(actualRoute:actualRoute cost:cost experimentId:experimentId latencyMs:latencyMs response:response variant:variant workId:workId) -- Record explicitly unverified, caller-reported API observations. Does not establish internal model state or improvement.
V P record-behavior-observe -> script why:"typed manual runner; stops at every judgement"
P record-experience-compare(workId:str baseline:str candidate:str preference:t3 observations:t1):saved=experience.compare(baseline:baseline candidate:candidate observations:observations preference:preference workId:workId) -- Record a provisional critic comparison tied to two actual image artifacts; does not claim user preference.
V P record-experience-compare -> script why:"typed manual runner; stops at every judgement"
P record-experience-investigate(workId:str hypothesis:str experiment:t1 references:t4):saved=experience.investigate(experiment:experiment hypothesis:hypothesis references:references workId:workId) -- Preserve an explicit hypothesis and proposed experiment without claiming the experiment ran.
V P record-experience-investigate -> script why:"typed manual runner; stops at every judgement"
P record-experience-note(workId:str lesson:str conditions:str invalidation:str evidence:t5):saved=experience.note(conditions:conditions evidence:evidence invalidation:invalidation lesson:lesson workId:workId) -- After work, preserve a small proposed lesson, applicability conditions, invalidation rules and existing evidence paths. Requires learning enabled; does not establish truth or authority.
V P record-experience-note -> script why:"typed manual runner; stops at every judgement"
P record-experience-trace(workId:str traceId:str eventKind:t6 payload:t1 references:t4):saved=experience.trace(eventKind:eventKind payload:payload references:references traceId:traceId workId:workId) -- Append a timestamped reported interaction observation with references; not an independently verified journey.
V P record-experience-trace -> script why:"typed manual runner; stops at every judgement"
P record-experiment-create(experimentId:str source:str launchRecipe:t1 resetRecipe:t1):saved=experiment.create(experimentId:experimentId launchRecipe:launchRecipe resetRecipe:resetRecipe source:source) -- Preserve an isolated experiment snapshot and declared recipes; does not execute recipes.
V P record-experiment-create -> script why:"typed manual runner; stops at every judgement"
P record-experiment-restore(experimentId:str restoreId:str):saved=experiment.restore(experimentId:experimentId restoreId:restoreId) -- Restore an intact experiment into a new isolated directory, refusing overwrite.
V P record-experiment-restore -> script why:"typed manual runner; stops at every judgement"
P record-orchestration-compile(source:str outputPath:t7):saved=orchestration.compile(outputPath:outputPath source:source) -- Compile a compact NEYVIA/1 program into a validated dependency graph with runtime, permission, budget, and proof contracts.
V P record-orchestration-compile -> script why:"typed manual runner; stops at every judgement"
P record-quality-challenge(workId:str arguments:t8):saved=quality.challenge(arguments:arguments workId:workId) -- Persist a proposed examination challenge pending operator review. Arguments: holdout, proposal.
V P record-quality-challenge -> script why:"typed manual runner; stops at every judgement"
P record-quality-compare(workId:str arguments:t9):saved=quality.compare(arguments:arguments workId:workId) -- Apply the same frozen instrument to real baseline and candidate artifacts. Arguments: instrument, baseline, candidate.
V P record-quality-compare -> script why:"typed manual runner; stops at every judgement"
P record-quality-examine(workId:str arguments:t10):saved=quality.examine(arguments:arguments workId:workId) -- Run all frozen examination instruments on supplied artifact targets. Arguments: holdout, targets.
V P record-quality-examine -> script why:"typed manual runner; stops at every judgement"
P record-quality-holdout(workId:str arguments:t11):saved=quality.holdout(arguments:arguments workId:workId) -- Seal an immutable examination with an instruments list. Arguments: i, spec.
V P record-quality-holdout -> script why:"typed manual runner; stops at every judgement"
P record-quality-instrument(workId:str arguments:t12):saved=quality.instrument(arguments:arguments workId:workId) -- Seal a json_numeric, image or trace_timing instrument specification. Arguments: i, spec.
V P record-quality-instrument -> script why:"typed manual runner; stops at every judgement"
P record-quality-measure(workId:str arguments:t13):saved=quality.measure(arguments:arguments workId:workId) -- Measure an actual scoped artifact and preserve a receipt. Arguments: instrument, target.
V P record-quality-measure -> script why:"typed manual runner; stops at every judgement"
P record-taste-correction(workId:str arguments:t14):saved=taste.correction(arguments:arguments workId:workId) -- Record a provisional contextual correction from real before/after artifacts. Arguments: context, before_path, after_path, correction.
V P record-taste-correction -> script why:"typed manual runner; stops at every judgement"
X A reported observation is mistaken for actual provider/model quality -> Keep evidenceVerified false and use a separately authorized real provider journey.
X A frozen source, instrument or saved record changes -> Completion is refused; inspect the owning source and create a new explicit trial.
F No provider model is invoked. No general quality, operator taste or skill improvement is established.
F Dependency provisioning, host rehearsal and skill mutation require their own fresh execution witness.
M local-records "Enable applicable collaboration preferences through the operator seam before a trial." src:"authored manual" state:verified
M local-records "Instrument criteria establish exactly the measured local artifact property. Preserve failed measurements." src:"authored manual" state:verified
