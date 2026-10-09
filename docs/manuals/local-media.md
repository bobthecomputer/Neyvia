<!-- Generated from manuals/cl/local-media.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# local-media

## evidence
CL 1
L local-media v1 -- Fresh retained browser, video and skill evidence
T t1 json:"{\"type\":\"string\",\"enum\":[\"domcontentloaded\",\"load\",\"networkidle\"]}"
T t2 json:"{\"type\":\"object\"}"
T t3 [json:"{\"type\":\"string\",\"enum\":[\"desktop\",\"phone\"]}"]
T t4 json:"{\"type\":\"string\",\"enum\":[\"dark\",\"light\"]}"
T t5 json:"{\"type\":\"boolean\",\"description\":\"Inline capped screenshots for the installed desktop Preview, which has no HTTP artifact route.\"}"
T t6 json:"{\"type\":\"object\",\"description\":\"Controls to exercise through Laya: actions [{kind: click|fill|select|press, label, value?, expect?}], expect [{kind: selector_text|text_present|selector_exists|url_contains, ...}].\"}"
T t7 json:"{\"type\":\"string\",\"description\":\"Optional report directory inside the active workspace. Omit to use the managed artifact directory.\"}"
T t8 json:"{\"type\":\"string\",\"enum\":[\"auto\",\"none\",\"local\"]}"
A preview.screenshot(url:str outputPath?:str fullPage?:bool width?:320..3840 height?:240..2160 waitFor?:str delayMs?:0..10000 waitUntil?:t1) -> t2 ! -- Capture a real PNG from a URL with Playwright or Chromium and return dimensions, SHA-256, and engine proof.
F verify-preview-screenshot "No authored observer check is bound to preview.screenshot" -> ask operator blocks:preview.screenshot
A preview.annotate(url:str rectangle:t2 comment?:str viewport?:t2 outputDir?:str delayMs?:0..10000) -> t2 ! -- Capture a preview, draw an operator-selected rectangle and comment, create a cropped region, and write a W3C-shaped annotation receipt with hashes.
F verify-preview-annotate "No authored observer check is bound to preview.annotate" -> ask operator blocks:preview.annotate
A preview.taste(url:str goal?:str#..600 viewports?:t3 colorScheme?:t4 waitFor?:str delayMs?:0..10000 includeImageData?:t5 journey?:t6 outputDir?:t7) -> t2 ! -- See and measure your own rendered UI before calling visual work done. Renders the page at desktop and phone widths, returns screenshots to inspect, and reports colliding text, overflow, contrast, typeface and colour discipline, tap targets, competing primary actions and box clutter with evidence and fixes. Optional journey: Laya exercises the controls the goal depends on and reports what it actually tested. Use this tool for a Laya browser journey: provide the page URL, goal, and journey actions with expected outcomes. Measurements inform judgment; they never certify beauty.
F verify-preview-taste "No authored observer check is bound to preview.taste" -> ask operator blocks:preview.taste
A video.digest(path:str outputDir?:str maxFrames?:1..36 maxSceneFrames?:0..24 sceneThreshold?:0.05..0.95 sceneScanSeconds?:1..3600 extractAudio?:bool transcribe?:t8 whisperModel?:str timeoutSeconds?:1..7200) -> t2 ! -- Convert a video into model-readable timestamped frames, scene-change frames, a storyboard, audio, optional local Whisper transcript, and a JSON manifest.
F verify-video-digest "No authored observer check is bound to video.digest" -> ask operator blocks:video.digest
A skill.live.iterate(skillId?:str path:str content:str expectedSha256?:str sessionId:str request?:str) -> t2 ! -- Validate and atomically revise a live session SKILL.md with optimistic conflict detection, an external backup, and durable version receipts.
F verify-skill-live-iterate "No authored observer check is bound to skill.live.iterate" -> ask operator blocks:skill.live.iterate
P preview-screenshot(url:str outputPath:str fullPage:bool width:320..3840 height:240..2160 waitFor:str delayMs:0..10000 waitUntil:t1):effect=preview.screenshot(delayMs:delayMs fullPage:fullPage height:height outputPath:outputPath url:url waitFor:waitFor waitUntil:waitUntil width:width) -- Capture and independently verify retained media bytes, requested inputs and persisted receipts
V P preview-screenshot -> script why:"typed manual runner; stops at every judgement"
P preview-annotate(url:str rectangle:t2 comment:str viewport:t2 outputDir:str delayMs:0..10000):effect=preview.annotate(comment:comment delayMs:delayMs outputDir:outputDir rectangle:rectangle url:url viewport:viewport) -- Capture and independently verify retained media bytes, requested inputs and persisted receipts
V P preview-annotate -> script why:"typed manual runner; stops at every judgement"
P preview-taste(url:str goal:str#..600 viewports:t3 colorScheme:t4 waitFor:str delayMs:0..10000 includeImageData:t5 journey:t6 outputDir:t7):effect=preview.taste(colorScheme:colorScheme delayMs:delayMs goal:goal includeImageData:includeImageData journey:journey outputDir:outputDir url:url viewports:viewports waitFor:waitFor) -- Capture and independently verify retained media bytes, requested inputs and persisted receipts
V P preview-taste -> script why:"typed manual runner; stops at every judgement"
P video-digest(path:str outputDir:str maxFrames:1..36 maxSceneFrames:0..24 sceneThreshold:0.05..0.95 sceneScanSeconds:1..3600 extractAudio:bool transcribe:t8 whisperModel:str timeoutSeconds:1..7200):effect=video.digest(extractAudio:extractAudio maxFrames:maxFrames maxSceneFrames:maxSceneFrames outputDir:outputDir path:path sceneScanSeconds:sceneScanSeconds sceneThreshold:sceneThreshold timeoutSeconds:timeoutSeconds transcribe:transcribe whisperModel:whisperModel) -- Capture and independently verify retained media bytes, requested inputs and persisted receipts
V P video-digest -> script why:"typed manual runner; stops at every judgement"
P skill-live-iterate(skillId:str path:str content:str expectedSha256:str sessionId:str request:str):effect=skill.live.iterate(content:content expectedSha256:expectedSha256 path:path request:request sessionId:sessionId skillId:skillId) -- Capture and independently verify retained media bytes, requested inputs and persisted receipts
V P skill-live-iterate -> script why:"typed manual runner; stops at every judgement"
X Retained proof changes after capture -> Restore the exact retained bytes or make a new capture and verify it.
F Remote authenticated pages and model-backed Laya journeys need account and provider authority.
M local-media "Capture pages in the current browser; verify PNG byte hashes and requested geometry." src:"authored manual" state:verified
M local-media "Video needs installed FFmpeg and FFprobe; bind actual selected frames, timestamps, storyboard, audio and transcript artifacts." src:"authored manual" state:verified
M local-media "Skill revisions retain loaded-version CAS, validated contents, preserved original, durable receipt and ledger. Session identity belongs to the host." src:"authored manual" state:verified
M local-media "Taste measures retained captures; it never certifies beauty." src:"authored manual" state:verified
