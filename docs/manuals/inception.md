<!-- Generated from manuals/cl/inception.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# inception

## release
CL 1
L inception v1 -- Pinned scratch Neyvia tests a candidate through T16 and T18
T t1 json:"{\"type\":\"object\"}"
T t2 json:"{\"type\":\"string\",\"enum\":[\"auto\",\"powershell\",\"python\",\"bash\",\"cmd\"]}"
T t3 json:"{\"type\":\"string\",\"enum\":[\".\"],\"default\":\".\"}"
S inception.coverage:t1=neyvia.inception.inventory()
S inception.last-run:t1=neyvia.inception.report()
A neyvia.inception.inventory() -> t1 -- Read every authoritative manual hash, procedure, input, judge and goal check
F verify-inventory "No authored observer check is bound to neyvia.inception.inventory" -> ask operator blocks:neyvia.inception.inventory
A neyvia.inception.report() -> t1 -- Recheck source hashes and T16/T18 proof bytes before returning releaseGate
C neyvia.inception.report report-present:neyvia.inception.report() .available == true
A terminal.exec(command:str#1.. shell?:t2 cwd?:str timeoutMs?:1..120000 maxOutputChars?:128..50000) -> t1 ! -- Run fresh source-bound C8 adapter admission and refusal checks, with the executable driver closure copied and hashed under the D run root.
C terminal.exec adapter-preflight-passed:matches(workspace.read(path:"c8-preflight-result.json") {properties:{content:{pattern:"\"preflightStatus\": \"C8-ADAPTER-PREFLIGHT-PASSED\"" type:"string"}} required:["content"] type:"object"})
C neyvia.inception.report report-present:neyvia.inception.report() .available == true
C workspace.read adapter-preflight-passed:matches(workspace.read(path:"c8-preflight-result.json") {properties:{content:{pattern:"\"preflightStatus\": \"C8-ADAPTER-PREFLIGHT-PASSED\"" type:"string"}} required:["content"] type:"object"})
P inspect-release():release=neyvia.inception.report() C report-present -- Read the last report with freshly revalidated evidence; a blocked release is a valid reported outcome
V P inspect-release -> script why:"typed manual runner; stops at every judgement"
P run-adapter-preflight(stateRoot?:t3):receipt=terminal.exec(command:"import sys,json; from pathlib import Path; sys.path.insert(0,\"C:/Users/user/Projects/nx-int-final/scripts\"); import c8_journey; result=c8_journey.preflight_contract(\"D:/NeyviaRuns/INTN/c8-cl-preflight\"); Path(\"c8-preflight-result.json\").write_text(json.dumps(result),encoding=\"utf-8\"); print(result[\"preflightStatus\"])" cwd:stateRoot maxOutputChars:50000 shell:"python" timeoutMs:120000) C adapter-preflight-passed -- Execute fresh C8 source-hash, deferred-slot, scoped-input, escape and bounds admission/refusal checks.
V P run-adapter-preflight -> script why:"typed manual runner; stops at every judgement"
X Unbound procedure or missing device/provider -> Author a source-hash-bound disposable journey or supply its required host; never call the row passed
X T16 background action unavailable or user input observed -> Keep the journey blocked; do not silently front the window or replay uncertain effects
X Evidence bytes or manual source changed -> Run again against the new explicit candidate and pin
F Only Notes write-and-pin and Settings read-preferences have authored UI bindings initially; all other rows remain release blockers
F The runner is exclusively headless until plan 20 C11 provides a verified isolated desktop; T18 browser proof never counts as T16 native proof
F Devices, microphone, editor, external model and public release journeys need their actual hosts and separate authority
M inception "Build into .agent_control/C8/build-headless with the local Vite runner and no dependency installation" src:"authored manual" state:verified
M inception "Run scripts/run_c8_inception.py --stable-ref <local commit> --stable-port 48754 --candidate-port 48755 --journey-port settings=48756 --workers 2 --build-dir .agent_control/C8/build-headless --state-root .agent_control/proofs/C8/report-c8c" src:"authored manual" state:verified
M inception "Exit 0 means every row passed. Exit 2 means the report was saved and release remains blocked" src:"authored manual" state:verified
M inception "Stable source is archived from Git in a separate scratch directory. Services use separate explicit ports and disposable state. No credentials or NAS are read; no push, merge or public promotion occurs" src:"authored manual" state:verified
M inception "Headless webPassed counts real rendered browser journeys; releaseGate stays false until every row has both T16 and T18 proof" src:"authored manual" state:verified
M inception "Parallel journeys use distinct explicitly supplied candidate ports and disposable state; no shared pane state between workers" src:"authored manual" state:verified
M inception "The Notes/Settings backend scope refuses all child-process and desktop launches; runtime/native checks outside that scope remain blocked" src:"authored manual" state:verified
M inception "Run scripts/prove_c8_report.py --port 48757 --report scripts/evidence/C8c.json to verify the real HTTP report tool and its failure paths" src:"authored manual" state:verified
