<!-- Generated from manuals/cl/local-environment.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-environment

## environment
CL 1
L local-environment v1 -- Pinned local interpreters and declared task effects
T t1 json:"{\"type\":\"object\"}"
T t2 [str#..4096]#..32
T t3 [{path:str#1..4096 sha256:str ~"^[a-fA-F0-9]{64}$"}]#1..8
A environment.create(environmentId:str lockPath:str timeout?:1..300) -> t1 ! -- Create and independently probe a pinned interpreter or run exact saved source and verify newly written declared file bytes
F verify-environment-create "No authored observer check is bound to environment.create" -> ask operator blocks:environment.create
A environment.run(manifestPath:str args:t2 timeout?:1..300 outputs?:t3) -> t1 ! -- Create and independently probe a pinned interpreter or run exact saved source and verify newly written declared file bytes
F verify-environment-run "No authored observer check is bound to environment.run" -> ask operator blocks:environment.run
P verify-environment-create(environmentId:str lockPath:str timeout:1..300):saved=environment.create(environmentId:environmentId lockPath:lockPath timeout:timeout) -- Create or reuse hash-pinned Python dependencies with a shared uv cache. Dependency installation requires a mutation grant.
V P verify-environment-create -> script why:"typed manual runner; stops at every judgement"
P verify-environment-run(manifestPath:str args:t2 timeout:1..300 outputs:t3):saved=environment.run(args:args manifestPath:manifestPath outputs:outputs timeout:timeout) -- Run Python in a saved dependency environment and preserve the argv-bound process receipt. CL additionally requires a scoped script and declared fresh output hashes; dependency isolation is not an OS sandbox.
V P verify-environment-run -> script why:"typed manual runner; stops at every judgement"
X An old matching output or forged process receipt is mistaken for a new effect -> Use a new declared output path and exact SHA256; completion rechecks bytes, script, argv and interpreter.
X The pinned lock or script changes after execution -> Completion is refused; preserve the original run and use a new explicit environment or script.
F Only declared new workspace output files establish the run effect. Other side effects require their own observer.
F Inline -c/-m execution, reused output files and absent declared output hashes remain CL frontier.
F A Python dependency environment is not an OS sandbox. Offline empty-lock proof does not establish external dependency installation.
M local-environment "Use only already installed uv and Python. Respect network, installation and workspace authority." src:"authored manual" state:verified
M local-environment "The creation proof uses a real interpreter probe. Run receipts bind actual argv, source/interpreter hashes and declared outputs." src:"authored manual" state:verified
