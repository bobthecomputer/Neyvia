<!-- Generated from manuals/cl/voice.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# voice

## overview
CL 1
L voice v1 -- Voice commands on the shared workspace bus
T t1{commands:json:"{\"type\":\"array\"}" apps:json:"{\"type\":\"array\"}" harnesses:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"object\"}"
T t3{status:str intent?:str args?:json:"{\"type\":\"object\"}" events?:json:"{\"type\":\"array\"}" ..}
S voice.grammar:t1=neyvia.voice.commands()
A neyvia.voice.command(text:str#..500 language?:str context?:t2 dryRun?:bool final?:bool requestId?:str) -> t3 -- Resolve grammar and execute through the existing shared command bus; dryRun emits nothing
C neyvia.voice.command resolved:neyvia.voice.command(dryRun:true text:text) .status == "dry_run"
C neyvia.voice.command notes-dry-run:neyvia.voice.command(dryRun:true text:"open notes") .status == "dry_run"
C neyvia.voice.command notes-dry-run:neyvia.voice.command(dryRun:true text:"open notes") .status == "dry_run"
C neyvia.voice.command resolved:neyvia.voice.command(dryRun:true text:text) .status == "dry_run"
P inspect-command(text:str#..500):parsed=neyvia.voice.command(dryRun:true text:text) C resolved -- Resolve a command without executing or opening a run
V P inspect-command -> script why:"typed manual runner; stops at every judgement"
P open-notes():opened=neyvia.voice.command(text:"open notes") C notes-dry-run -- Open Notes with the same bus used by the user
V P open-notes -> script why:"typed manual runner; stops at every judgement"
J visible-approval approve|deny:"Exactly which waiting request is visible and authorized?" -- Do not guess between chats or approve through a model tool; use the owner voice route with the visible session ID.
V J visible-approval -> human:operator why:"explicit choice required"
X A retry duplicates a voice action -> Reuse the original requestId; do not submit the command under a new ID.
X A stale window sends another chat -> Supply the originating clientId and current sessionId; the UI compares both before sending.
X Multiple requests are visible -> Select one explicit approval; never guess.
F Physical microphone and packed Tauri microphone prompt require host proof.
F No wake word, always-listening mode, custom phrases, or text-to-speech reply.
M voice "INDEX state Â· actions Â· checks Â· procedures Â· judgement points Â· pitfalls Â· frontier" src:"authored manual" state:verified
M voice "WHAT spoken (or typed) commands that move and act in Neyvia: \"open notes\", \"new codex chat in dictation\", \"approve\". Not prompt dictation (that is the dictation manual): a command is parsed, never inserted as text." src:"authored manual" state:verified
M voice "GRAMMAR deterministic, no model call; English and French phrasings; backend `src/grant_agent/neyvia_voice.py`; contract `plans/15-handoff.md` \"## T3\"." src:"authored manual" state:verified
M voice "LIST `neyvia.voice.commands()` â†’ `{commands:[{intent, description, examples[]}], apps:[{id,label,aliases,ready}], harnesses:[{id,label}]}`; desktop/browser `voice_commands_command`." src:"authored manual" state:verified
M voice "LOG one line per command in `<state root>/.neyvia/voice-commands.jsonl` `{at, text, language, intent, status, ms}`; no audio." src:"authored manual" state:verified
M voice "USER SIDE hold Ctrl+Alt+Space (or tap it, talk, tap again), or press **Voice** in the bottom strip, or launcher \"Say a command\"; the card above the strip shows the words so far, then what happened; it also has a box to type a command. Esc cancels." src:"authored manual" state:verified
M voice "AUDIO the same engine as dictation (Phonon-2 through `/api/ui/dictation/stream`, Qwen for French, the browser's speech input when the engine is missing)." src:"authored manual" state:verified
M voice "SCREEN READERS every answer is spoken through a polite live region (refusals and failures assertive); the card's status line is a live region too." src:"authored manual" state:verified
M voice "HELP Ctrl+/ (or ? outside a text box, or \"what can I say\") opens \"Keyboard and voice\": every shortcut and every command; the voice half comes from `voice_commands_command`, else the UI's built-in copy." src:"authored manual" state:verified
M voice "`neyvia.voice.command(text, context?, dryRun?, requestId?)` â†’ `{status: done|dry_run|no_match|ambiguous|refused|failed, intent, args, say, events[], receipt?, choices[], error}`; UI path `voice_command_command` with the same payload." src:"authored manual" state:verified
M voice "CONTEXT `{stage, sessionId, view: chat|new|home, approvalIds[], clientId}` = what is on Paul's screen; approve/deny/stop/send act only on it." src:"authored manual" state:verified
M voice "INTENTS app.open Â· pane.show Â· stage.close Â· launcher.open Â· dashboard.open Â· session.open Â· newchat.open Â· composer.send Â· run.answer Â· run.stop Â· view.theme Â· view.layout Â· sidebar.toggle Â· dictation.start Â· voice.help." src:"authored manual" state:verified
M voice "EFFECT each intent emits bus events (`app.open {app,suite,target?}`, `stage.close`, `launcher.open {query}`, `dashboard.open`, `session.open {id,title}`, `newchat.open {app, folder?:{path,name}, prompt?, dictate}`, `composer.send {sessionId|\"new\"}`, `sidebar.toggle {hidden}`, `dictation.start {target: composer|notes}`, `voice.help`, plus existing `pane.show`, `view.theme`, `view.layout`, `notify`); run.answer calls `broker.answer`, run.stop calls `broker.stop`." src:"authored manual" state:verified
M voice "`neyvia.app.open(app, target?)` opens any ready launcher app on Paul's screen (bus `app.open`)." src:"authored manual" state:verified
M voice "`dryRun: true` parses and resolves only: no event, no broker call. Use it to check what a phrase would do." src:"authored manual" state:verified
M voice "Understood: answer `status == \"done\"` and `intent` is the one meant; `args` name the right app/chat/folder." src:"authored manual" state:verified
M voice "Screen reacted: every `events[].id` acknowledged on the bus (`/api/ui/ack ok:true`); for app.open the user side reports `app-state` for that app." src:"authored manual" state:verified
M voice "Approve worked: `receipt.state` is no longer `waiting_approval` for `context.sessionId`; a `notify` \"Approved: â€¦\" was emitted." src:"authored manual" state:verified
M voice "Nothing ran by mistake: for `no_match`, `ambiguous`, `refused` the answer has `events: []` and no receipt." src:"authored manual" state:verified
M voice "UI journey: `node web/a11y/nx-voice-journey.mjs --url <vite> [--live] [--wav <file>]` â†’ `journey.json` checks all `ok: true`, screenshots per step." src:"authored manual" state:verified
M voice "Accessibility: `node web/a11y/nx-a11y-audit.mjs --url <vite> --axe <axe.min.js>` â†’ TOTAL has no critical or serious, `noFocusRing: 0`." src:"authored manual" state:verified
M voice "OPEN AN APP `neyvia.voice.command(\"open notes\", dryRun=true)` â†’ check `args.app` â†’ run without dryRun â†’ check the ack." src:"authored manual" state:verified
M voice "NEW CHAT FOR PAUL \"new codex chat in dictation\" â†’ `newchat.open` opens New chat with Codex and the folder; prompt dictation starts in the box; Paul (or \"send\") sends. A command never starts a run on its own." src:"authored manual" state:verified
M voice "APPROVE WHAT'S ON SCREEN Paul says \"approve\" with the chat open â†’ context.sessionId's pending approval answered â†’ [judge: exactly one approval on screen]." src:"authored manual" state:verified
M voice "AMBIGUOUS answer `status: ambiguous` â†’ show `choices` (full phrases) â†’ Paul picks one â†’ resend that phrase with a new requestId." src:"authored manual" state:verified
M voice "NOT UNDERSTOOD `no_match` â†’ show the nearest phrases and the help sheet; do not guess." src:"authored manual" state:verified
M voice "JUDGE more than one thing could be approved (a chat approval and a Neyvia tool approval, or two notices): the grammar answers `ambiguous`; ask Paul which, never pick." src:"authored manual" state:verified
M voice "JUDGE a folder or chat name matches several: offer the choices; a single clear winner only." src:"authored manual" state:verified
M voice "JUDGE \"send\" while the box holds dictated text Paul hasn't seen: the UI sends what is visible; if the text came from a voice prompt seconds ago, read it back first." src:"authored manual" state:verified
M voice "Same `requestId` twice â†’ the first receipt comes back and nothing runs again; a new command needs a new id." src:"authored manual" state:verified
M voice "The answer can arrive as `ok: false` for refused/no_match: it is still a receipt (`status`, `say`), not a transport failure." src:"authored manual" state:verified
M voice "Events are applied from the answer and again from the SSE stream: the bus drops the second copy by id; never re-emit them by hand." src:"authored manual" state:verified
M voice "Bus actions from voice are moments: after a reconnect they are not replayed (an old \"open notes\" must not reopen Notes)." src:"authored manual" state:verified
M voice "Ctrl+Alt+Space is AltGr+Space on AZERTY keyboards; it still works, but a layout tool may take it. The strip button and the launcher entry always work." src:"authored manual" state:verified
M voice "The speech engine may take several minutes to start: the UI records and waits; commands said meanwhile are kept, not lost." src:"authored manual" state:verified
M voice "Headless browsers without speech input: the card says to type the command; typed commands take exactly the same path." src:"authored manual" state:verified
M voice "No wake word or always-listening mode: a key, a button or the launcher starts listening." src:"authored manual" state:verified
M voice "No custom phrases yet (Paul's own names for things); grammar changes go through `neyvia_voice.py`." src:"authored manual" state:verified
M voice "Spoken confirmation (text-to-speech) of answers is not built: answers are shown and read by the screen reader only." src:"authored manual" state:verified
M voice "Desktop (Tauri/WebView2) microphone prompt for voice is the dictation one; not yet proven in the packed app." src:"authored manual" state:verified
