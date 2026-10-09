<!-- Generated from manuals/cl/local-browser-sdk.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-browser-sdk

## evidence
CL 1
L local-browser-sdk v1 -- Actual owned browser and SDK evidence
T t1 json:"{\"type\":\"object\"}"
T t2 [json:"{\"type\":\"object\"}"]
T t3 json:"{\"type\":\"object\",\"properties\":{\"goal\":{},\"options\":{},\"progress\":{},\"action_receipts\":{},\"query\":{},\"result\":{},\"previous\":{},\"decision_profile\":{},\"advisory_field\":{},\"evidence\":{}},\"additionalProperties\":false}"
T t4 str ~"^[a-fA-F0-9]{64}$"
S local-browser-sdk.private-browser:t1=neyvia.perception.browser.observe()
A neyvia.perception.browser.open(url:str) -> t1 ! -- Open a private browser session for exactly this origin; no user profile or downloads.
F verify-perception-browser-open "No authored observer check is bound to neyvia.perception.browser.open" -> ask operator blocks:neyvia.perception.browser.open
A neyvia.perception.browser.action(browserId:str revision:str element:str action:"fill"|"click" value?:str) -> t1 ! -- Act on a fresh DOM projection; stale revisions fail before any effect. Caller must authorize the action.
F verify-perception-browser-action "No authored observer check is bound to neyvia.perception.browser.action" -> ask operator blocks:neyvia.perception.browser.action
A neyvia.perception.browser.close(browserId:str) -> t1 ! -- Close this owned browser session.
F verify-perception-browser-close "No authored observer check is bound to neyvia.perception.browser.close" -> ask operator blocks:neyvia.perception.browser.close
A neyvia.app_sdk.preview(project:str device?:str port:1..65535) -> t1 ! -- Open an SDK app in Mobile Studio's existing phone frame. port is the explicit running Neyvia backend port.
F verify-app_sdk-preview "No authored observer check is bound to neyvia.app_sdk.preview" -> ask operator blocks:neyvia.app_sdk.preview
A neyvia.app_sdk.verify(project:str url:str clSource?:str native?:t1 steps?:t2) -> t1 ! -- Run the app's goals through T18 web perception and optional T16 native inspection; failed goals refuse completion. Uses an explicit running-app URL.
F verify-app_sdk-verify "No authored observer check is bound to neyvia.app_sdk.verify" -> ask operator blocks:neyvia.app_sdk.verify
A neyvia.browser.decide(tabId:str question:str context?:t3) -> t1 -- Acquire fresh native DOM and ask the attached LAYA service; explicit unavailable fallback, advisory only.
F verify-browser-decide "No authored observer check is bound to neyvia.browser.decide" -> ask operator blocks:neyvia.browser.decide
A workspace.read(path:str maxChars?:1..100000 offset?:0.. startLine?:1.. endLine?:1.. expectedSha256?:t4) -> t1 -- Read the exact mounted-runtime witness bytes
C workspace.read sdk-native-observation:matches(workspace.read(path:observation) .content {allOf:[{pattern:"\"actualMountedControlChangesState\"\\s*:\\s*true"} {pattern:"\"nativeAppPixelsPresent\"\\s*:\\s*true"} {pattern:"\"nativePhoneActuallyVisible\"\\s*:\\s*true"} {pattern:"\"previewActualPositiveCL\"\\s*:\\s*true"} {pattern:"\"currentManualEffectReceipt\"\\s*:\\s*true"}] type:"string"})
C workspace.read sdk-native-observation:matches(workspace.read(path:observation) .content {allOf:[{pattern:"\"actualMountedControlChangesState\"\\s*:\\s*true"} {pattern:"\"nativeAppPixelsPresent\"\\s*:\\s*true"} {pattern:"\"nativePhoneActuallyVisible\"\\s*:\\s*true"} {pattern:"\"previewActualPositiveCL\"\\s*:\\s*true"} {pattern:"\"currentManualEffectReceipt\"\\s*:\\s*true"}] type:"string"})
P perception-browser-open(url:str):effect=neyvia.perception.browser.open(url:url) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P perception-browser-open -> script why:"typed manual runner; stops at every judgement"
P perception-browser-action(browserId:str revision:str element:str action:"fill"|"click" value:str):effect=neyvia.perception.browser.action(action:action browserId:browserId element:element revision:revision value:value) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P perception-browser-action -> script why:"typed manual runner; stops at every judgement"
P perception-browser-close(browserId:str):effect=neyvia.perception.browser.close(browserId:browserId) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P perception-browser-close -> script why:"typed manual runner; stops at every judgement"
P app_sdk-preview(project:str device:str port:1..65535):effect=neyvia.app_sdk.preview(device:device port:port project:project) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P app_sdk-preview -> script why:"typed manual runner; stops at every judgement"
P app_sdk-verify(project:str url:str clSource:str native:t1 steps:t2):effect=neyvia.app_sdk.verify(clSource:clSource native:native project:project steps:steps url:url) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P app_sdk-verify -> script why:"typed manual runner; stops at every judgement"
P browser-decide(tabId:str question:str context:t3):effect=neyvia.browser.decide(context:context question:question tabId:tabId) -- Execute the actual browser or SDK journey and independently verify fresh owner state
V P browser-decide -> script why:"typed manual runner; stops at every judgement"
P prove-sdk-mounted-observation(observation:str):mounted=workspace.read(path:observation) C sdk-native-observation -- The actual mounted SDK child realm changes shared state and paints native iframe content
V P prove-sdk-mounted-observation -> script why:"typed manual runner; stops at every judgement"
X Observed revision or retained proof changes -> Observe again and run the requested operation against current state; never accept stale evidence.
X Phone layout passes but the iframe is blank -> Require the mounted child identity, a real increment and native pixels. A separate same-URL context cannot replace the child realm.
F Visible WebView2 promotion needs an allowed desktop and actual native import plus fresh observed DOM. This task prohibits visible windows.
M local-browser-sdk "Use actual configured Neyvia headless contexts; require fresh observed revisions before DOM actions." src:"authored manual" state:verified
M local-browser-sdk "SDK verification executes the authored contract journey and retains source hashes, actual state and screenshot bytes." src:"authored manual" state:verified
M local-browser-sdk "SDK previews need a mounted Phone iframe and delivered owner event." src:"authored manual" state:verified
M local-browser-sdk "LAYA decisions require the actual frozen local service and durable advisory receipts; advice grants no action authority." src:"authored manual" state:verified
M local-browser-sdk "Observe the sole owned private browser session before acting; multiple sessions require an existing host-selected identity. Transport stamps stay internal. The observer starts no browser." src:"authored manual" state:verified
