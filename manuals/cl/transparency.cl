CL 1
L transparency v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Thinking and actions in every chat"},"proofs-e-chat":{"title":"PROOFS-e chat stream, recovery and recorded evidence"},"filmbugs":{"title":"Launch film behavior contracts"}},"clVersion":"1.1","id":"transparency","kind":"workflow","schema":"neyvia.manual.v1","schemas":{"neyvia.view.transparency":"t1","proofs-e-chat.status":"t2"},"tool_metadata":{"neyvia.verify.status":{},"neyvia.view.transparency":{"mutability_class":"none"}},"proofs":{"area":"transparency"}}
-- @proof {"id":"transparency.helper-reports","phase":"invariant","claim":"Claude Code agent-message and task-notification envelopes render as compact Helper reported items with the helper name and report body; harness authority framing never becomes a human bubble.","checkedAt":["grant_agent.connected_sessions.claude_items.helper_reports","grant_agent.connected_sessions.claude_transcript.ItemStore._helper_notices","web/src/neyvia/next/NxThread.jsx"],"impact":["Launch film behavior"]}
-- @proof {"id":"transparency.quiet-unreported","phase":"invariant","claim":"At most one not-reported reasoning notice appears per human turn, and none when that turn displays tool steps; shared and explicitly withheld reasoning remain available.","checkedAt":["web/src/neyvia/next/nxTransparencyModel.js:visibleTranscriptItems"],"impact":["Launch film behavior"]}
T t1{level:json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}" ..}
T t2{..}
T t3 json:"{\"type\":\"object\",\"properties\":{},\"additionalProperties\":false}"
T t4{transparency:"everything"|"summaries"|"minimal" ..}
T t5{ok:true level:str ..}
T t6{level:json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}"}
T t7{ok:bool available:bool complete:bool ..}
T t8 json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}"
L transparency.overview v1 -- Thinking and actions in every chat
-- @record {"chapter":"overview","data":{"args":{},"inputs":{"$cl_type":"t3"},"shape":{"$cl_type":"t4"},"tool":"neyvia.view.transparency.state"},"key":"current","section":"state"}
S transparency.current:{transparency:"everything"|"summaries"|"minimal" ..}=neyvia.view.transparency.state()
-- @record {"chapter":"overview","data":{"effect":"Persist the display level and notify every connected UI; capture still retains all provider-exposed data","pre":"Owner-authorized workspace; choose an advertised display level","returns":{"$cl_type":"t5"},"reversible":true,"schema":"neyvia.view.transparency","tool":"neyvia.view.transparency"},"key":"choose","section":"actions"}
A neyvia.view.transparency(level:json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}") -> {ok:true level:str ..} ! -- Persist the display level and notify every connected UI; capture still retains all provider-exposed data
C neyvia.view.transparency retained:neyvia.view.transparency.state() .transparency == level
-- @record {"chapter":"overview","data":{"args":{},"expect":{"op":"eq","path":"transparency","value":{"$input":"level"}},"tool":"neyvia.view.transparency.state"},"key":"retained","section":"checks"}
C neyvia.view.transparency.state retained:neyvia.view.transparency.state() .transparency == level
-- @record {"chapter":"overview","data":{"goal":"Change the thread detail level and verify durable workspace state","inputs":{"$cl_type":"t6"},"steps":[{"action":"choose","args":{"level":{"$input":"level"}},"check":"retained","save":"choice"}]},"key":"choose-detail","section":"procedures"}
P choose-detail(level:json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}"):choice=neyvia.view.transparency(level:level) C retained -- Change the thread detail level and verify durable workspace state
V P choose-detail -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Verify the actual effect through fresh owning observers","inputs":{"$cl_type":"t1"},"steps":[{"action":"choose","args":{"level":{"$input":"level"}},"save":"effect"}]},"key":"verify-effect-choose","section":"procedures"}
P verify-effect-choose(level:json:"{\"type\":\"string\",\"enum\":[\"everything\",\"summaries\",\"minimal\"]}"):effect=neyvia.view.transparency(level:level) -- Verify the actual effect through fresh owning observers
V P verify-effect-choose -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"failure":"A provider does not share reasoning","recovery":"Keep at most one quiet availability notice per turn; omit it when visible tool steps explain the turn; never invent hidden thought text"},"key":"0","section":"pitfalls"}
X A provider does not share reasoning -> Keep at most one quiet availability notice per turn; omit it when visible tool steps explain the turn; never invent hidden thought text
-- @record {"chapter":"overview","data":{"failure":"Output is shortened on a thread page","recovery":"Expand the tool to request the existing full-output command; retain any explicit transport limit notice"},"key":"1","section":"pitfalls"}
X Output is shortened on a thread page -> Expand the tool to request the existing full-output command; retain any explicit transport limit notice
-- @record {"chapter":"overview","data":"Native desktop interaction and providers/models not present in the T22 real-turn receipt remain unverified","key":"0","section":"frontier"}
F Native desktop interaction and providers/models not present in the T22 real-turn receipt remain unverified
-- @record {"chapter":"overview","data":"Settings > Thinking and actions: Show everything is default; Summaries keeps details a click away; Minimal retains messages, failures and reasoning availability notices.","key":"0","section":"guidance"}
M transparency "Settings > Thinking and actions: Show everything is default; Summaries keeps details a click away; Minimal retains messages, failures and reasoning availability notices." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Codex app-server requests detailed summaries and retains exposed summary/content; opaque underlying reasoning is never decrypted or reconstructed.","key":"1","section":"guidance"}
M transparency "Codex app-server requests detailed summaries and retains exposed summary/content; opaque underlying reasoning is never decrypted or reconstructed." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Claude Code 2.1.295 launches and resumes with --thinking-display summarized; terminal hook settings also request showThinkingSummaries. Readable provider thinking blocks are labelled Reasoning summary and collapsed by default. Redacted blocks and opaque signatures are never decoded; an availability notice appears only when no summary is available for the turn.","key":"2","section":"guidance"}
M transparency "Claude Code 2.1.295 launches and resumes with --thinking-display summarized; terminal hook settings also request showThinkingSummaries. Readable provider thinking blocks are labelled Reasoning summary and collapsed by default. Redacted blocks and opaque signatures are never decoded; an availability notice appears only when no summary is available for the turn." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"OpenCode ACP and native history expose provider thought chunks and tool parts; DeepSeek reasoning depends on the selected provider and model.","key":"3","section":"guidance"}
M transparency "OpenCode ACP and native history expose provider thought chunks and tool parts; DeepSeek reasoning depends on the selected provider and model." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Every harness uses reasoning/tool/diff items with command, arguments, output, exit code and duration where exposed or measured; missing measurements remain explicit.","key":"4","section":"guidance"}
M transparency "Every harness uses reasoning/tool/diff items with command, arguments, output, exit code and duration where exposed or measured; missing measurements remain explicit." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Thinking settings are display controls, independent of model effort or provider capture. No global CLI settings are modified.","key":"5","section":"guidance"}
M transparency "Thinking settings are display controls, independent of model effort or provider capture. No global CLI settings are modified." src:"authored manual" state:verified
L transparency.proofs-e-chat v1 -- PROOFS-e chat stream, recovery and recorded evidence
-- @record {"chapter":"proofs-e-chat","data":{"args":{},"inputs":{"$cl_type":"t2"},"shape":{"$cl_type":"t7"},"tool":"neyvia.verify.status"},"key":"receipt","section":"state"}
S transparency.receipt:{ok:bool available:bool complete:bool ..}=neyvia.verify.status()
-- @record {"chapter":"proofs-e-chat","data":{"effect":"Read the latest real chat-contract verification receipt and its completeness boundary","pre":"Selected local workspace; observation does not replay any chat action","returns":{"$cl_type":"t8"},"reversible":true,"schema":"proofs-e-chat.status","tool":"neyvia.verify.status"},"key":"status","section":"actions"}
A neyvia.verify.status() -> json:"{\"type\":\"object\",\"required\":[\"ok\",\"available\",\"complete\"]}" ! -- Read the latest real chat-contract verification receipt and its completeness boundary
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-chat","data":{"args":{},"expect":{"op":"eq","path":"ok","value":true},"tool":"neyvia.verify.status"},"key":"observed","section":"checks"}
C neyvia.verify.status observed:neyvia.verify.status() .ok == true
-- @record {"chapter":"proofs-e-chat","data":{"goal":"Read fresh proof status without restarting any chat or provider","inputs":{"$cl_type":"t2"},"steps":[{"action":"status","args":{},"check":"observed","save":"receipt"}]},"key":"read-chat-proof-receipt","section":"procedures"}
P read-chat-proof-receipt():receipt=neyvia.verify.status() C observed -- Read fresh proof status without restarting any chat or provider
V P read-chat-proof-receipt -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"proofs-e-chat","data":{"failure":"Pending text remains Thinking after a crashed owner","recovery":"Observe actual run status; wait during grace, watch a live run, settle only a terminal or unowned turn; retain partial output"},"key":"0","section":"pitfalls"}
X Pending text remains Thinking after a crashed owner -> Observe actual run status; wait during grace, watch a live run, settle only a terminal or unowned turn; retain partial output
-- @record {"chapter":"proofs-e-chat","data":{"failure":"A tool result label is treated as successful execution","recovery":"Recorded failure/cancellation outranks hints; command and diff cards display actual recorded evidence"},"key":"1","section":"pitfalls"}
X A tool result label is treated as successful execution -> Recorded failure/cancellation outranks hints; command and diff cards display actual recorded evidence
-- @record {"chapter":"proofs-e-chat","data":"Real pure stream/recovery/presentation and scratch desktop polling boundaries; rendered UI and provider execution are separate proof boundaries","key":"0","section":"frontier"}
F Real pure stream/recovery/presentation and scratch desktop polling boundaries; rendered UI and provider execution are separate proof boundaries
-- @record {"chapter":"proofs-e-chat","data":"recovery.interrupted: recovery.interrupted","key":"0","section":"guidance"}
M transparency "recovery.interrupted: recovery.interrupted" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"recovery.decision: recovery.decision","key":"1","section":"guidance"}
M transparency "recovery.decision: recovery.decision" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"recovery.recorded: recovery.recorded","key":"2","section":"guidance"}
M transparency "recovery.recorded: recovery.recorded" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"recovery.unowned: recovery.unowned","key":"3","section":"guidance"}
M transparency "recovery.unowned: recovery.unowned" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"recovery.quiet: recovery.quiet","key":"4","section":"guidance"}
M transparency "recovery.quiet: recovery.quiet" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"recovery.merge: recovery.merge","key":"5","section":"guidance"}
M transparency "recovery.merge: recovery.merge" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"activity.href: activity.href","key":"6","section":"guidance"}
M transparency "activity.href: activity.href" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"activity.duration: activity.duration","key":"7","section":"guidance"}
M transparency "activity.duration: activity.duration" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.streamState: New streams begin empty without fabricated reply or activity","key":"8","section":"guidance"}
M transparency "proofs-e.chat.streamState: New streams begin empty without fabricated reply or activity" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.normalizedCalls: Tool projections preserve actual ids,input,output and errors; failure results override legacy completed status","key":"9","section":"guidance"}
M transparency "proofs-e.chat.normalizedCalls: Tool projections preserve actual ids,input,output and errors; failure results override legacy completed status" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.trace: Live and receipt-only projections preserve reasoning summaries and normalized recorded tool evidence","key":"10","section":"guidance"}
M transparency "proofs-e.chat.trace: Live and receipt-only projections preserve reasoning summaries and normalized recorded tool evidence" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.streamTransition: Every real streamed event updates its actual answer identity,Unicode text,summary or id-merged tool call preserving earlier evidence","key":"11","section":"guidance"}
M transparency "proofs-e.chat.streamTransition: Every real streamed event updates its actual answer identity,Unicode text,summary or id-merged tool call preserving earlier evidence" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.pollDelivery: Only an active poll delivers exact snapshot events with its observed cursor; stop ignores late responses","key":"12","section":"guidance"}
M transparency "proofs-e.chat.pollDelivery: Only an active poll delivers exact snapshot events with its observed cursor; stop ignores late responses" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.phase: Recorded failure and cancelled or uncertain states take precedence over pending/success hints","key":"13","section":"guidance"}
M transparency "proofs-e.chat.phase: Recorded failure and cancelled or uncertain states take precedence over pending/success hints" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.chip: Recorded outcomes survive chip-label guesses; labels alone never turn tool results into success","key":"14","section":"guidance"}
M transparency "proofs-e.chat.chip: Recorded outcomes survive chip-label guesses; labels alone never turn tool results into success" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.activity: Activity cards retain real command/input/output and category, readable app title,summary,phase and distinct indexed identity","key":"15","section":"guidance"}
M transparency "proofs-e.chat.activity: Activity cards retain real command/input/output and category, readable app title,summary,phase and distinct indexed identity" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.visibleActivity: Answer/progress deltas stay out of tool cards and one item-id lifecycle preserves earlier command and completion output","key":"16","section":"guidance"}
M transparency "proofs-e.chat.visibleActivity: Answer/progress deltas stay out of tool cards and one item-id lifecycle preserves earlier command and completion output" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.surfaces: Every canonical workspace surface is addressable and installed studio/workflow destinations remain available","key":"17","section":"guidance"}
M transparency "proofs-e.chat.surfaces: Every canonical workspace surface is addressable and installed studio/workflow destinations remain available" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.presentation: Recorded commands,reads,created files and edits show authentic shell,cwd,exit,error,output and bounded diffs with correct line numbers","key":"18","section":"guidance"}
M transparency "proofs-e.chat.presentation: Recorded commands,reads,created files and edits show authentic shell,cwd,exit,error,output and bounded diffs with correct line numbers" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.commandSummary: Collapsed command summaries preserve signed Windows exit code and actual stdout/stderr line counts","key":"19","section":"guidance"}
M transparency "proofs-e.chat.commandSummary: Collapsed command summaries preserve signed Windows exit code and actual stdout/stderr line counts" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.stringField: Lenient recorded field parsing decodes escapes and exposes truncation while dropping incomplete escapes","key":"20","section":"guidance"}
M transparency "proofs-e.chat.stringField: Lenient recorded field parsing decodes escapes and exposes truncation while dropping incomplete escapes" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.utf16: Repair genuine NUL-heavy UTF16 misreads while preserving ordinary output","key":"21","section":"guidance"}
M transparency "proofs-e.chat.utf16: Repair genuine NUL-heavy UTF16 misreads while preserving ordinary output" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.diff: Unified diff lines retain add/remove/context types and independently advancing old/new hunk line numbers","key":"22","section":"guidance"}
M transparency "proofs-e.chat.diff: Unified diff lines retain add/remove/context types and independently advancing old/new hunk line numbers" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.family: Gateway and harness aliases resolve the actual command/edit/write/read/search/fetch family","key":"23","section":"guidance"}
M transparency "proofs-e.chat.family: Gateway and harness aliases resolve the actual command/edit/write/read/search/fetch family" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.safe-display: Activity display redacts secrets and inline media without mutating the actual transport; readable ordinary output survives","key":"24","section":"guidance"}
M transparency "proofs-e.chat.safe-display: Activity display redacts secrets and inline media without mutating the actual transport; readable ordinary output survives" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"proofs-e.chat.desktop-stream: Flat and wrapped desktop polls return only complete UTF8 rows with byte cursors and refuse unsafe turn ids","key":"25","section":"guidance"}
M transparency "proofs-e.chat.desktop-stream: Flat and wrapped desktop polls return only complete UTF8 rows with byte cursors and refuse unsafe turn ids" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"Startup: scripts/proofs-e-chat.mjs --root <owned-scratch> invokes seven actual recovery/stream/poll/presentation/desktop procedures and rejects semantic corruption","key":"26","section":"guidance"}
M transparency "Startup: scripts/proofs-e-chat.mjs --root <owned-scratch> invokes seven actual recovery/stream/poll/presentation/desktop procedures and rejects semantic corruption" src:"authored manual" state:verified
-- @record {"chapter":"proofs-e-chat","data":"Desktop proof uses only get_agent_chat_stream_command local file fast path; flat and Tauri-wrapped arguments share its byte cursor and turn-id checks","key":"27","section":"guidance"}
M transparency "Desktop proof uses only get_agent_chat_stream_command local file fast path; flat and Tauri-wrapped arguments share its byte cursor and turn-id checks" src:"authored manual" state:verified
L transparency.filmbugs v1 -- Launch film behavior contracts
-- @record {"chapter":"filmbugs","section":"guidance","key":"0","data":"Claude Code agent-message and task-notification envelopes render as compact Helper reported items with the helper name and report body; harness authority framing never becomes a human bubble."}
M transparency "Claude Code agent-message and task-notification envelopes render as compact Helper reported items with the helper name and report body; harness authority framing never becomes a human bubble." src:"authored manual" state:verified
-- @record {"chapter":"filmbugs","section":"guidance","key":"1","data":"At most one not-reported reasoning notice appears per human turn, and none when that turn displays tool steps; shared and explicitly withheld reasoning remain available."}
M transparency "At most one not-reported reasoning notice appears per human turn, and none when that turn displays tool steps; shared and explicitly withheld reasoning remain available." src:"authored manual" state:verified
