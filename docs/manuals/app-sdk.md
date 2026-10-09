<!-- Generated from manuals/cl/app-sdk.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# app-sdk

## overview
CL 1
L app-sdk v1 -- Generate, inspect and prove an app through one user and agent state
T t1 json:"{\"type\":\"object\"}"
T t2 "web"|"pwa"|"expo"|"desktop"
T t3 [json:"{\"type\":\"object\"}"]
T t4{ok:true ..}
T t5 "web"|"pwa"|"expo"|"desktop"|"ios"|"android"
S app-sdk.app:t1=neyvia.app_sdk.state(project:project)
A neyvia.app_sdk.new(path:str name:str kind:t2) -> t1 ! -- Generate an app with a CL 1.1 manual, shared user/agent state and executable running-app goals. Does not install dependencies.
F verify-sdk-new "No authored observer check is bound to neyvia.app_sdk.new" -> ask operator blocks:neyvia.app_sdk.new
A neyvia.app_sdk.describe(project:str) -> t1 -- Read an SDK app's manual, platforms and current build/verification receipts.
F verify-sdk-describe "No authored observer check is bound to neyvia.app_sdk.describe" -> ask operator blocks:neyvia.app_sdk.describe
A neyvia.app_sdk.state(project:str) -> t1 -- Read the app's persisted shared state; the user UI and agents use this exact store.
F verify-sdk-state "No authored observer check is bound to neyvia.app_sdk.state" -> ask operator blocks:neyvia.app_sdk.state
A neyvia.app_sdk.action(project:str url:str name:str arguments?:t1 clSource?:str native?:t1) -> t1 ! -- Apply a typed app action through its exact running reducer using T18; the same shared state updates the user UI.
F verify-sdk-action "No authored observer check is bound to neyvia.app_sdk.action" -> ask operator blocks:neyvia.app_sdk.action
A neyvia.app_sdk.verify(project:str url:str clSource?:str native?:t1 steps?:t3) -> t4 ! -- Run the app's goals through T18 web perception and optional T16 native inspection; failed goals refuse completion. Uses an explicit running-app URL.
F verify-sdk-verify "No authored observer check is bound to neyvia.app_sdk.verify" -> ask operator blocks:neyvia.app_sdk.verify
A neyvia.app_sdk.preview(project:str device?:str port:1..65535) -> t1 ! -- Open an SDK app in Mobile Studio's existing phone frame. port is the explicit running Neyvia backend port.
F verify-sdk-preview "No authored observer check is bound to neyvia.app_sdk.preview" -> ask operator blocks:neyvia.app_sdk.preview
A neyvia.app_sdk.build(project:str platform:t5) -> t1 ! -- Build an SDK app using installed local tools. Offline web builds carry source hashes; unavailable native toolchains are reported, never installed.
F verify-sdk-build "No authored observer check is bound to neyvia.app_sdk.build" -> ask operator blocks:neyvia.app_sdk.build
A neyvia.app_sdk.toolchain(platform:"android"|"ios" project?:str) -> t1 -- Observe the exact native build owner toolchain without starting adb, an emulator or downloads
C neyvia.app_sdk.toolchain android-ready:neyvia.app_sdk.toolchain(platform:"android") .ready == true
C neyvia.app_sdk.toolchain android-ready:neyvia.app_sdk.toolchain(platform:"android") .ready == true
P inspect(project:str):manual=neyvia.app_sdk.describe(project:project); state=neyvia.app_sdk.state(project:project) -- Read the generated app manual and shared state
V P inspect -> script why:"typed manual runner; stops at every judgement"
P verify-effect-sdk-new(path:str name:str kind:t2):effect=neyvia.app_sdk.new(kind:kind name:name path:path) -- Verify the actual effect through fresh owning observers
V P verify-effect-sdk-new -> script why:"typed manual runner; stops at every judgement"
P verify-effect-sdk-action(project:str url:str name:str):effect=neyvia.app_sdk.action(name:name project:project url:url) -- Verify the actual effect through fresh owning observers
V P verify-effect-sdk-action -> script why:"typed manual runner; stops at every judgement"
P verify-effect-sdk-build(project:str platform:t5):effect=neyvia.app_sdk.build(platform:platform project:project) -- Verify the actual effect through fresh owning observers
V P verify-effect-sdk-build -> script why:"typed manual runner; stops at every judgement"
P inspect-android-toolchain():android=neyvia.app_sdk.toolchain(platform:"android") C android-ready -- Prove Android App Factory prerequisites from the existing build owner; this does not claim an APK build or device installation
V P inspect-android-toolchain -> script why:"typed manual runner; stops at every judgement"
X App goal check fails -> Read exact failed goal and live receipt, repair source, rebuild and re-run; never weaken the goal to mark done
X Native toolchain is unavailable -> Read needsPaul; never install or silently substitute a web build for a native build
F Expo native packaging, device installs and signed release delivery depend on local toolchains and separate authorization
M app-sdk "Generated app CL1.1 manuals define state, typed actions, runtime goal checks and procedures." src:"authored manual" state:verified
M app-sdk "Autopilot callers set appGoal and scope neyvia.app_sdk.verify; it re-runs the live journey before completed." src:"authored manual" state:verified
M app-sdk "app_sdk.verify and app_sdk.action mutate the explicitly scoped app; they are external actions." src:"authored manual" state:verified
M app-sdk "Every generation/build/action/verification claims its project in the work board and releases the claim after returning." src:"authored manual" state:verified
