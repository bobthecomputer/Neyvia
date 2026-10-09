CL 1
L voice v1 -- Authored executable manual
-- @manual {"chapters":{"overview":{"title":"Voice commands on the shared workspace bus"}},"clVersion":"1.1","id":"voice","kind":"environment","schema":"neyvia.manual.v1","schemas":{"neyvia.app.open":"t1","neyvia.voice.command":"t2","neyvia.voice.commands":"t3"},"tool_metadata":{"neyvia.voice.command":{"mutability_class":"none"}}}
T t1{app:str target?:str ..}
T t2 json:"{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\",\"maxLength\":500},\"language\":{\"type\":\"string\"},\"context\":{\"type\":\"object\"},\"dryRun\":{\"type\":\"boolean\"},\"final\":{\"type\":\"boolean\"},\"requestId\":{\"type\":\"string\"}},\"required\":[\"text\"],\"allOf\":[{\"properties\":{\"text\":{\"not\":{\"enum\":[\"\"]}}}}]}"
T t3{..}
T t4 json:"{\"type\":\"object\",\"properties\":{}}"
T t5{commands:json:"{\"type\":\"array\"}" apps:json:"{\"type\":\"array\"}" harnesses:json:"{\"type\":\"array\"}" ..}
T t6{status:str intent?:str args?:json:"{\"type\":\"object\"}" events?:json:"{\"type\":\"array\"}" ..}
T t7{text:str#..500 ..}
L voice.overview v1 -- Voice commands on the shared workspace bus
-- @record {"chapter":"overview","data":{"args":{},"inputs":{"$cl_type":"t4"},"shape":{"$cl_type":"t5"},"tool":"neyvia.voice.commands"},"key":"grammar","section":"state"}
S voice.grammar:{commands:json:"{\"type\":\"array\"}" apps:json:"{\"type\":\"array\"}" harnesses:json:"{\"type\":\"array\"}" ..}=neyvia.voice.commands()
-- @record {"chapter":"overview","data":{"effect":"Resolve grammar and execute through the existing shared command bus; dryRun emits nothing","pre":"Final transcript; owner approval must use the owner voice UI","returns":{"$cl_type":"t6"},"reversible":false,"schema":"neyvia.voice.command","tool":"neyvia.voice.command"},"key":"command","section":"actions"}
A neyvia.voice.command(text:str#..500 language?:str context?:json:"{\"type\":\"object\"}" dryRun?:bool final?:bool requestId?:str) -> {status:str intent?:str args?:json:"{\"type\":\"object\"}" events?:json:"{\"type\":\"array\"}" ..} -- Resolve grammar and execute through the existing shared command bus; dryRun emits nothing
C neyvia.voice.command resolved:neyvia.voice.command(dryRun:true text:text) .status == "dry_run"
C neyvia.voice.command notes-dry-run:neyvia.voice.command(dryRun:true text:"open notes") .status == "dry_run"
-- @record {"chapter":"overview","data":{"args":{"dryRun":true,"text":"open notes"},"expect":{"op":"eq","path":"status","value":"dry_run"},"tool":"neyvia.voice.command"},"key":"notes-dry-run","section":"checks"}
C neyvia.voice.command notes-dry-run:neyvia.voice.command(dryRun:true text:"open notes") .status == "dry_run"
-- @record {"chapter":"overview","data":{"args":{"dryRun":true,"text":{"$input":"text"}},"expect":{"op":"eq","path":"status","value":"dry_run"},"tool":"neyvia.voice.command"},"key":"resolved","section":"checks"}
C neyvia.voice.command resolved:neyvia.voice.command(dryRun:true text:text) .status == "dry_run"
-- @record {"chapter":"overview","data":{"goal":"Resolve a command without executing or opening a run","inputs":{"$cl_type":"t7"},"steps":[{"action":"command","args":{"dryRun":true,"text":{"$input":"text"}},"check":"resolved","save":"parsed"}]},"key":"inspect-command","section":"procedures"}
P inspect-command(text:str#..500):parsed=neyvia.voice.command(dryRun:true text:text) C resolved -- Resolve a command without executing or opening a run
V P inspect-command -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"goal":"Open Notes with the same bus used by the user","inputs":{"$cl_type":"t4"},"steps":[{"action":"command","args":{"text":"open notes"},"check":"notes-dry-run","save":"opened"}]},"key":"open-notes","section":"procedures"}
P open-notes():opened=neyvia.voice.command(text:"open notes") C notes-dry-run -- Open Notes with the same bus used by the user
V P open-notes -> script why:"typed manual runner; stops at every judgement"
-- @record {"chapter":"overview","data":{"constraints":"Do not guess between chats or approve through a model tool; use the owner voice route with the visible session ID.","options":["approve","deny"],"question":"Exactly which waiting request is visible and authorized?"},"key":"visible-approval","section":"judge"}
J visible-approval approve|deny:"Exactly which waiting request is visible and authorized?" -- Do not guess between chats or approve through a model tool; use the owner voice route with the visible session ID.
V J visible-approval -> human:operator why:"explicit choice required"
-- @record {"chapter":"overview","data":{"failure":"A retry duplicates a voice action","recovery":"Reuse the original requestId; do not submit the command under a new ID."},"key":"0","section":"pitfalls"}
X A retry duplicates a voice action -> Reuse the original requestId; do not submit the command under a new ID.
-- @record {"chapter":"overview","data":{"failure":"A stale window sends another chat","recovery":"Supply the originating clientId and current sessionId; the UI compares both before sending."},"key":"1","section":"pitfalls"}
X A stale window sends another chat -> Supply the originating clientId and current sessionId; the UI compares both before sending.
-- @record {"chapter":"overview","data":{"failure":"Multiple requests are visible","recovery":"Select one explicit approval; never guess."},"key":"2","section":"pitfalls"}
X Multiple requests are visible -> Select one explicit approval; never guess.
-- @record {"chapter":"overview","data":"Physical microphone and packed Tauri microphone prompt require host proof.","key":"0","section":"frontier"}
F Physical microphone and packed Tauri microphone prompt require host proof.
-- @record {"chapter":"overview","data":"No wake word, always-listening mode, custom phrases, or text-to-speech reply.","key":"1","section":"frontier"}
F No wake word, always-listening mode, custom phrases, or text-to-speech reply.
-- @record {"chapter":"overview","data":"INDEX state Â· actions Â· checks Â· procedures Â· judgement points Â· pitfalls Â· frontier","key":"0","section":"guidance"}
M voice "INDEX state Â· actions Â· checks Â· procedures Â· judgement points Â· pitfalls Â· frontier" src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"WHAT spoken (or typed) commands that move and act in Neyvia: \"open notes\", \"new codex chat in dictation\", \"approve\". Not prompt dictation (that is the dictation manual): a command is parsed, never inserted as text.","key":"1","section":"guidance"}
M voice "WHAT spoken (or typed) commands that move and act in Neyvia: \"open notes\", \"new codex chat in dictation\", \"approve\". Not prompt dictation (that is the dictation manual): a command is parsed, never inserted as text." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"GRAMMAR deterministic, no model call; English and French phrasings; backend `src/grant_agent/neyvia_voice.py`; contract `plans/15-handoff.md` \"## T3\".","key":"2","section":"guidance"}
M voice "GRAMMAR deterministic, no model call; English and French phrasings; backend `src/grant_agent/neyvia_voice.py`; contract `plans/15-handoff.md` \"## T3\"." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"LIST `neyvia.voice.commands()` â†’ `{commands:[{intent, description, examples[]}], apps:[{id,label,aliases,ready}], harnesses:[{id,label}]}`; desktop/browser `voice_commands_command`.","key":"3","section":"guidance"}
M voice "LIST `neyvia.voice.commands()` â†’ `{commands:[{intent, description, examples[]}], apps:[{id,label,aliases,ready}], harnesses:[{id,label}]}`; desktop/browser `voice_commands_command`." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"LOG one line per command in `<state root>/.neyvia/voice-commands.jsonl` `{at, text, language, intent, status, ms}`; no audio.","key":"4","section":"guidance"}
M voice "LOG one line per command in `<state root>/.neyvia/voice-commands.jsonl` `{at, text, language, intent, status, ms}`; no audio." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"USER SIDE hold Ctrl+Alt+Space (or tap it, talk, tap again), or press **Voice** in the bottom strip, or launcher \"Say a command\"; the card above the strip shows the words so far, then what happened; it also has a box to type a command. Esc cancels.","key":"5","section":"guidance"}
M voice "USER SIDE hold Ctrl+Alt+Space (or tap it, talk, tap again), or press **Voice** in the bottom strip, or launcher \"Say a command\"; the card above the strip shows the words so far, then what happened; it also has a box to type a command. Esc cancels." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"AUDIO the same engine as dictation (Phonon-2 through `/api/ui/dictation/stream`, Qwen for French, the browser's speech input when the engine is missing).","key":"6","section":"guidance"}
M voice "AUDIO the same engine as dictation (Phonon-2 through `/api/ui/dictation/stream`, Qwen for French, the browser's speech input when the engine is missing)." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"SCREEN READERS every answer is spoken through a polite live region (refusals and failures assertive); the card's status line is a live region too.","key":"7","section":"guidance"}
M voice "SCREEN READERS every answer is spoken through a polite live region (refusals and failures assertive); the card's status line is a live region too." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"HELP Ctrl+/ (or ? outside a text box, or \"what can I say\") opens \"Keyboard and voice\": every shortcut and every command; the voice half comes from `voice_commands_command`, else the UI's built-in copy.","key":"8","section":"guidance"}
M voice "HELP Ctrl+/ (or ? outside a text box, or \"what can I say\") opens \"Keyboard and voice\": every shortcut and every command; the voice half comes from `voice_commands_command`, else the UI's built-in copy." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"`neyvia.voice.command(text, context?, dryRun?, requestId?)` â†’ `{status: done|dry_run|no_match|ambiguous|refused|failed, intent, args, say, events[], receipt?, choices[], error}`; UI path `voice_command_command` with the same payload.","key":"9","section":"guidance"}
M voice "`neyvia.voice.command(text, context?, dryRun?, requestId?)` â†’ `{status: done|dry_run|no_match|ambiguous|refused|failed, intent, args, say, events[], receipt?, choices[], error}`; UI path `voice_command_command` with the same payload." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"CONTEXT `{stage, sessionId, view: chat|new|home, approvalIds[], clientId}` = what is on Paul's screen; approve/deny/stop/send act only on it.","key":"10","section":"guidance"}
M voice "CONTEXT `{stage, sessionId, view: chat|new|home, approvalIds[], clientId}` = what is on Paul's screen; approve/deny/stop/send act only on it." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"INTENTS app.open Â· pane.show Â· stage.close Â· launcher.open Â· dashboard.open Â· session.open Â· newchat.open Â· composer.send Â· run.answer Â· run.stop Â· view.theme Â· view.layout Â· sidebar.toggle Â· dictation.start Â· voice.help.","key":"11","section":"guidance"}
M voice "INTENTS app.open Â· pane.show Â· stage.close Â· launcher.open Â· dashboard.open Â· session.open Â· newchat.open Â· composer.send Â· run.answer Â· run.stop Â· view.theme Â· view.layout Â· sidebar.toggle Â· dictation.start Â· voice.help." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"EFFECT each intent emits bus events (`app.open {app,suite,target?}`, `stage.close`, `launcher.open {query}`, `dashboard.open`, `session.open {id,title}`, `newchat.open {app, folder?:{path,name}, prompt?, dictate}`, `composer.send {sessionId|\"new\"}`, `sidebar.toggle {hidden}`, `dictation.start {target: composer|notes}`, `voice.help`, plus existing `pane.show`, `view.theme`, `view.layout`, `notify`); run.answer calls `broker.answer`, run.stop calls `broker.stop`.","key":"12","section":"guidance"}
M voice "EFFECT each intent emits bus events (`app.open {app,suite,target?}`, `stage.close`, `launcher.open {query}`, `dashboard.open`, `session.open {id,title}`, `newchat.open {app, folder?:{path,name}, prompt?, dictate}`, `composer.send {sessionId|\"new\"}`, `sidebar.toggle {hidden}`, `dictation.start {target: composer|notes}`, `voice.help`, plus existing `pane.show`, `view.theme`, `view.layout`, `notify`); run.answer calls `broker.answer`, run.stop calls `broker.stop`." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"`neyvia.app.open(app, target?)` opens any ready launcher app on Paul's screen (bus `app.open`).","key":"13","section":"guidance"}
M voice "`neyvia.app.open(app, target?)` opens any ready launcher app on Paul's screen (bus `app.open`)." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"`dryRun: true` parses and resolves only: no event, no broker call. Use it to check what a phrase would do.","key":"14","section":"guidance"}
M voice "`dryRun: true` parses and resolves only: no event, no broker call. Use it to check what a phrase would do." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Understood: answer `status == \"done\"` and `intent` is the one meant; `args` name the right app/chat/folder.","key":"15","section":"guidance"}
M voice "Understood: answer `status == \"done\"` and `intent` is the one meant; `args` name the right app/chat/folder." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Screen reacted: every `events[].id` acknowledged on the bus (`/api/ui/ack ok:true`); for app.open the user side reports `app-state` for that app.","key":"16","section":"guidance"}
M voice "Screen reacted: every `events[].id` acknowledged on the bus (`/api/ui/ack ok:true`); for app.open the user side reports `app-state` for that app." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Approve worked: `receipt.state` is no longer `waiting_approval` for `context.sessionId`; a `notify` \"Approved: â€¦\" was emitted.","key":"17","section":"guidance"}
M voice "Approve worked: `receipt.state` is no longer `waiting_approval` for `context.sessionId`; a `notify` \"Approved: â€¦\" was emitted." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Nothing ran by mistake: for `no_match`, `ambiguous`, `refused` the answer has `events: []` and no receipt.","key":"18","section":"guidance"}
M voice "Nothing ran by mistake: for `no_match`, `ambiguous`, `refused` the answer has `events: []` and no receipt." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"UI journey: `node web/a11y/nx-voice-journey.mjs --url <vite> [--live] [--wav <file>]` â†’ `journey.json` checks all `ok: true`, screenshots per step.","key":"19","section":"guidance"}
M voice "UI journey: `node web/a11y/nx-voice-journey.mjs --url <vite> [--live] [--wav <file>]` â†’ `journey.json` checks all `ok: true`, screenshots per step." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Accessibility: `node web/a11y/nx-a11y-audit.mjs --url <vite> --axe <axe.min.js>` â†’ TOTAL has no critical or serious, `noFocusRing: 0`.","key":"20","section":"guidance"}
M voice "Accessibility: `node web/a11y/nx-a11y-audit.mjs --url <vite> --axe <axe.min.js>` â†’ TOTAL has no critical or serious, `noFocusRing: 0`." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"OPEN AN APP `neyvia.voice.command(\"open notes\", dryRun=true)` â†’ check `args.app` â†’ run without dryRun â†’ check the ack.","key":"21","section":"guidance"}
M voice "OPEN AN APP `neyvia.voice.command(\"open notes\", dryRun=true)` â†’ check `args.app` â†’ run without dryRun â†’ check the ack." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"NEW CHAT FOR PAUL \"new codex chat in dictation\" â†’ `newchat.open` opens New chat with Codex and the folder; prompt dictation starts in the box; Paul (or \"send\") sends. A command never starts a run on its own.","key":"22","section":"guidance"}
M voice "NEW CHAT FOR PAUL \"new codex chat in dictation\" â†’ `newchat.open` opens New chat with Codex and the folder; prompt dictation starts in the box; Paul (or \"send\") sends. A command never starts a run on its own." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"APPROVE WHAT'S ON SCREEN Paul says \"approve\" with the chat open â†’ context.sessionId's pending approval answered â†’ [judge: exactly one approval on screen].","key":"23","section":"guidance"}
M voice "APPROVE WHAT'S ON SCREEN Paul says \"approve\" with the chat open â†’ context.sessionId's pending approval answered â†’ [judge: exactly one approval on screen]." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"AMBIGUOUS answer `status: ambiguous` â†’ show `choices` (full phrases) â†’ Paul picks one â†’ resend that phrase with a new requestId.","key":"24","section":"guidance"}
M voice "AMBIGUOUS answer `status: ambiguous` â†’ show `choices` (full phrases) â†’ Paul picks one â†’ resend that phrase with a new requestId." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"NOT UNDERSTOOD `no_match` â†’ show the nearest phrases and the help sheet; do not guess.","key":"25","section":"guidance"}
M voice "NOT UNDERSTOOD `no_match` â†’ show the nearest phrases and the help sheet; do not guess." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"JUDGE more than one thing could be approved (a chat approval and a Neyvia tool approval, or two notices): the grammar answers `ambiguous`; ask Paul which, never pick.","key":"26","section":"guidance"}
M voice "JUDGE more than one thing could be approved (a chat approval and a Neyvia tool approval, or two notices): the grammar answers `ambiguous`; ask Paul which, never pick." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"JUDGE a folder or chat name matches several: offer the choices; a single clear winner only.","key":"27","section":"guidance"}
M voice "JUDGE a folder or chat name matches several: offer the choices; a single clear winner only." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"JUDGE \"send\" while the box holds dictated text Paul hasn't seen: the UI sends what is visible; if the text came from a voice prompt seconds ago, read it back first.","key":"28","section":"guidance"}
M voice "JUDGE \"send\" while the box holds dictated text Paul hasn't seen: the UI sends what is visible; if the text came from a voice prompt seconds ago, read it back first." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Same `requestId` twice â†’ the first receipt comes back and nothing runs again; a new command needs a new id.","key":"29","section":"guidance"}
M voice "Same `requestId` twice â†’ the first receipt comes back and nothing runs again; a new command needs a new id." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"The answer can arrive as `ok: false` for refused/no_match: it is still a receipt (`status`, `say`), not a transport failure.","key":"30","section":"guidance"}
M voice "The answer can arrive as `ok: false` for refused/no_match: it is still a receipt (`status`, `say`), not a transport failure." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Events are applied from the answer and again from the SSE stream: the bus drops the second copy by id; never re-emit them by hand.","key":"31","section":"guidance"}
M voice "Events are applied from the answer and again from the SSE stream: the bus drops the second copy by id; never re-emit them by hand." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Bus actions from voice are moments: after a reconnect they are not replayed (an old \"open notes\" must not reopen Notes).","key":"32","section":"guidance"}
M voice "Bus actions from voice are moments: after a reconnect they are not replayed (an old \"open notes\" must not reopen Notes)." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Ctrl+Alt+Space is AltGr+Space on AZERTY keyboards; it still works, but a layout tool may take it. The strip button and the launcher entry always work.","key":"33","section":"guidance"}
M voice "Ctrl+Alt+Space is AltGr+Space on AZERTY keyboards; it still works, but a layout tool may take it. The strip button and the launcher entry always work." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"The speech engine may take several minutes to start: the UI records and waits; commands said meanwhile are kept, not lost.","key":"34","section":"guidance"}
M voice "The speech engine may take several minutes to start: the UI records and waits; commands said meanwhile are kept, not lost." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Headless browsers without speech input: the card says to type the command; typed commands take exactly the same path.","key":"35","section":"guidance"}
M voice "Headless browsers without speech input: the card says to type the command; typed commands take exactly the same path." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"No wake word or always-listening mode: a key, a button or the launcher starts listening.","key":"36","section":"guidance"}
M voice "No wake word or always-listening mode: a key, a button or the launcher starts listening." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"No custom phrases yet (Paul's own names for things); grammar changes go through `neyvia_voice.py`.","key":"37","section":"guidance"}
M voice "No custom phrases yet (Paul's own names for things); grammar changes go through `neyvia_voice.py`." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Spoken confirmation (text-to-speech) of answers is not built: answers are shown and read by the screen reader only.","key":"38","section":"guidance"}
M voice "Spoken confirmation (text-to-speech) of answers is not built: answers are shown and read by the screen reader only." src:"authored manual" state:verified
-- @record {"chapter":"overview","data":"Desktop (Tauri/WebView2) microphone prompt for voice is the dictation one; not yet proven in the packed app.","key":"39","section":"guidance"}
M voice "Desktop (Tauri/WebView2) microphone prompt for voice is the dictation one; not yet proven in the packed app." src:"authored manual" state:verified
