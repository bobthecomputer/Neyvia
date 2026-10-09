<!-- Generated from manuals/cl/transparency.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# transparency

## overview
CL 1
L transparency v1 -- Thinking and actions in every chat
T t1{transparency:"everything"|"summaries"|"minimal" ..}
T t2 json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}"
T t3{ok:true level:str ..}
S transparency.current:t1=neyvia.view.transparency.state()
A neyvia.view.transparency(level:t2) -> t3 ! -- Persist the display level and notify every connected UI; capture still retains all provider-exposed data
C neyvia.view.transparency retained:neyvia.view.transparency.state() .transparency == level
C neyvia.view.transparency.state retained:neyvia.view.transparency.state() .transparency == level
P choose-detail(level:t2):choice=neyvia.view.transparency(level:level) C retained -- Change the thread detail level and verify durable workspace state
V P choose-detail -> script why:"typed manual runner; stops at every judgement"
P verify-effect-choose(level:t2):effect=neyvia.view.transparency(level:level) -- Verify the actual effect through fresh owning observers
V P verify-effect-choose -> script why:"typed manual runner; stops at every judgement"
X A provider does not share reasoning -> Keep the explicit provider availability notice; never invent hidden thought text
X Output is shortened on a thread page -> Expand the tool to request the existing full-output command; retain any explicit transport limit notice
F Native desktop interaction and providers/models not present in the T22 real-turn receipt remain unverified
M transparency "Settings > Thinking and actions: Show everything is default; Summaries keeps details a click away; Minimal retains messages, failures and reasoning availability notices." src:"authored manual" state:verified
M transparency "Codex app-server requests detailed summaries and retains exposed summary/content; opaque underlying reasoning is never decrypted or reconstructed." src:"authored manual" state:verified
M transparency "Claude Code enables thinking per launch; stream-json and terminal transcripts expose only blocks supplied by Claude, including redacted/empty availability." src:"authored manual" state:verified
M transparency "OpenCode ACP and native history expose provider thought chunks and tool parts; DeepSeek reasoning depends on the selected provider and model." src:"authored manual" state:verified
M transparency "Every harness uses reasoning/tool/diff items with command, arguments, output, exit code and duration where exposed or measured; missing measurements remain explicit." src:"authored manual" state:verified
M transparency "Thinking settings are display controls, independent of model effort or provider capture. No global CLI settings are modified." src:"authored manual" state:verified

## proofs-e-chat
CL 1
L transparency v1 -- PROOFS-e chat stream, recovery and recorded evidence
T t1{ok:bool available:bool complete:bool ..}
T t2 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
S transparency.receipt:t1=neyvia.verify.status()
A neyvia.verify.status() -> t2 -- Read the latest real chat-contract verification receipt and its completeness boundary
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
P read-chat-proof-receipt():receipt=neyvia.verify.status() C observed -- Read fresh proof status without restarting any chat or provider
V P read-chat-proof-receipt -> script why:"typed manual runner; stops at every judgement"
X Pending text remains Thinking after a crashed owner -> Observe actual run status; wait during grace, watch a live run, settle only a terminal or unowned turn; retain partial output
X A tool result label is treated as successful execution -> Recorded failure/cancellation outranks hints; command and diff cards display actual recorded evidence
F Real pure stream/recovery/presentation and scratch desktop polling boundaries; rendered UI and provider execution are separate proof boundaries
M transparency "recovery.interrupted: recovery.interrupted" src:"authored manual" state:verified
M transparency "recovery.decision: recovery.decision" src:"authored manual" state:verified
M transparency "recovery.recorded: recovery.recorded" src:"authored manual" state:verified
M transparency "recovery.unowned: recovery.unowned" src:"authored manual" state:verified
M transparency "recovery.quiet: recovery.quiet" src:"authored manual" state:verified
M transparency "recovery.merge: recovery.merge" src:"authored manual" state:verified
M transparency "activity.href: activity.href" src:"authored manual" state:verified
M transparency "activity.duration: activity.duration" src:"authored manual" state:verified
M transparency "proofs-e.chat.streamState: New streams begin empty without fabricated reply or activity" src:"authored manual" state:verified
M transparency "proofs-e.chat.normalizedCalls: Tool projections preserve actual ids,input,output and errors; failure results override legacy completed status" src:"authored manual" state:verified
M transparency "proofs-e.chat.trace: Live and receipt-only projections preserve reasoning summaries and normalized recorded tool evidence" src:"authored manual" state:verified
M transparency "proofs-e.chat.streamTransition: Every real streamed event updates its actual answer identity,Unicode text,summary or id-merged tool call preserving earlier evidence" src:"authored manual" state:verified
M transparency "proofs-e.chat.pollDelivery: Only an active poll delivers exact snapshot events with its observed cursor; stop ignores late responses" src:"authored manual" state:verified
M transparency "proofs-e.chat.phase: Recorded failure and cancelled or uncertain states take precedence over pending/success hints" src:"authored manual" state:verified
M transparency "proofs-e.chat.chip: Recorded outcomes survive chip-label guesses; labels alone never turn tool results into success" src:"authored manual" state:verified
M transparency "proofs-e.chat.activity: Activity cards retain real command/input/output and category, readable app title,summary,phase and distinct indexed identity" src:"authored manual" state:verified
M transparency "proofs-e.chat.visibleActivity: Answer/progress deltas stay out of tool cards and one item-id lifecycle preserves earlier command and completion output" src:"authored manual" state:verified
M transparency "proofs-e.chat.surfaces: Every canonical workspace surface is addressable and installed studio/workflow destinations remain available" src:"authored manual" state:verified
M transparency "proofs-e.chat.presentation: Recorded commands,reads,created files and edits show authentic shell,cwd,exit,error,output and bounded diffs with correct line numbers" src:"authored manual" state:verified
M transparency "proofs-e.chat.commandSummary: Collapsed command summaries preserve signed Windows exit code and actual stdout/stderr line counts" src:"authored manual" state:verified
M transparency "proofs-e.chat.stringField: Lenient recorded field parsing decodes escapes and exposes truncation while dropping incomplete escapes" src:"authored manual" state:verified
M transparency "proofs-e.chat.utf16: Repair genuine NUL-heavy UTF16 misreads while preserving ordinary output" src:"authored manual" state:verified
M transparency "proofs-e.chat.diff: Unified diff lines retain add/remove/context types and independently advancing old/new hunk line numbers" src:"authored manual" state:verified
M transparency "proofs-e.chat.family: Gateway and harness aliases resolve the actual command/edit/write/read/search/fetch family" src:"authored manual" state:verified
M transparency "proofs-e.chat.safe-display: Activity display redacts secrets and inline media without mutating the actual transport; readable ordinary output survives" src:"authored manual" state:verified
M transparency "proofs-e.chat.desktop-stream: Flat and wrapped desktop polls return only complete UTF8 rows with byte cursors and refuse unsafe turn ids" src:"authored manual" state:verified
M transparency "Startup: scripts/proofs-e-chat.mjs --root <owned-scratch> invokes seven actual recovery/stream/poll/presentation/desktop procedures and rejects semantic corruption" src:"authored manual" state:verified
M transparency "Desktop proof uses only get_agent_chat_stream_command local file fast path; flat and Tauri-wrapped arguments share its byte cursor and turn-id checks" src:"authored manual" state:verified
