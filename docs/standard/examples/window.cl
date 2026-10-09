CL 1
-- Windows window layer through the T16 driver: src/grant_agent/neyvia_cua.py (DEFINITIONS, target, verify_values),
-- neyvia_cua_mcp.py, manuals/computer-use.manual.json. The runtime block is the real GPT-6 Luna proof run
-- (scripts/evidence/T16-luna.json, calls 1, 9, 13, 17, 19): read the window, append text, verify, click Apply, re-read.
-- Today's format for the same content: today/window.*

-- L0
L win v1 tools:neyvia.cua untrusted -- native Windows apps driven in the background (UIA); Paul watches the preview

-- L1
T el{role:word label?:str h?:handle value?:str rect?:rect can?:[word] disabled?:bool focus?:bool}
T window{window_id:id title:str app:word pid:int rect:rect minimized?:bool}
S win.windows:[window] = win.windows()
S win.window:[el] = win.inspect(window_id)
A win.windows() -> [window] -- only windows of apps Paul allowed in this session
I win.windows reads:session.allow
A win.inspect(window_id:id query?:str max_elements?:1..2000) -> [el] -- every inspect re-issues element handles
I win.inspect reads:UIA(window_id) bounds:"2000 elements, depth 12"
A win.verify(el:handle value:str timeout_ms?:0..10000) -> {status:satisfied|unsatisfied|unknown stable:bool} = cua.verify(expect:[{element:{selector:{role:el.role label_contains:el.label} value_equals:value}}])
I win.verify reads:UIA.ValuePattern(el) -- stable readback, sampled until timeout
A win.set_value(el:handle value:str) ~ = cua.action(tool:set_value args:{el value})
I win.set_value writes:el.value ui:preview.outline undo:win.set_value(el value:previous.value) ask:"Paul, when the label matches delete|send|pay|submit|publish|…" -- background; focus and cursor unchanged
C win.set_value value-is: win.verify(el value).status=="satisfied"
A win.type_text(el:handle text:str) ~ = cua.action(tool:type_text args:{el text})
I win.type_text writes:el.value ui:preview.outline undo:win.set_value(el value:previous.value) ask:"Paul, for dangerous labels"
C win.type_text value-is: win.verify(el value:previous.value+text).status=="satisfied"
A win.click(el:handle) ! = cua.action(tool:click args:{el delivery_mode:background})
I win.click writes:"app-defined" ui:preview.outline undo:none ask:"Paul, for dangerous labels; others none: the target app is allowed" -- the driver often cannot see the effect
C win.click shows(text:str): len(win.inspect(window_id query:text))>0
A win.press_key(key:str) ! = cua.action(tool:press_key args:{key})
I win.press_key writes:"focused control" undo:none ask:"Paul, for dangerous targets"
C win.press_key changed: win.inspect(window_id)!=previous
A win.launch_app(app:str reason:str) ! = request_app(app reason)
I win.launch_app writes:session.allow ask:"Paul, within 120s" undo:none
C win.launch_app allowed: win.windows() has app
A win.wait(timeout_ms:0..600000) -> {note:str paulActions:[str]} -- while Paul holds control
I win.wait reads:shared-log

-- L2
J right-element act|look-again: "Is this element the field the task means, in an allowed app?" -- match role, label, position; two equal labels: ask Paul
P set-field-and-verify(window_id:id el:handle value:str): win.inspect(window_id); J right-element=act; win.set_value(el value)
X refused:paused_by_user -> win.wait(); read the note and paulActions; continue from the new state
X refused:app_not_allowed -> win.launch_app(app reason); never work around the allow-list
X refused:background_unavailable -> prefer set_value or invoke on an element; foreground only if the session allows it, and say so
X stale -> handled by the runtime: the handle re-binds to the newest inspect or the do returns R stale
X denied_by_user or approval_timeout -> do not retry; choose a reversible path
F canvas and custom-drawn surfaces without UIA peers -> pixel clicks on a capture only
Q right-field "is @0 still the field labelled Task input?" -> J right-element blocks:win.set_value
V J right-element -> model:small why:"role, label and rect in context"

-- runtime (real run; numeric handles are element handles of the newest inspect)
K session @s1 app:T16NativeProbe control:agent
K user Paul did:[set_value,set_value,click] note:"Authorized bounded Luna proof on the disposable native app."
S win.window 21237500 "T16 Built Native Probe" app:T16NativeProbe.exe pid:52480 [97,110,446,263] total:7 complete:false @h1
E window "T16 Built Native Probe"
 E edit "Task input" @0 "initial agent build cycle Paul checked UI joined agent continued after UI Luna verified" [122,173,390,20] can:set_value
 E button "Apply" @1 - [122,223,390,36] can:invoke
 E text "Applied: initial agent build cycle Paul checked UI joined agent continued after UI Luna verified"
 E titlebar - @2 "T16 Built Native Probe" [114,113,428,28] can:set_value
  E menubar "Système"
   E menuitem "Système" @3 - [98,118,22,22] can:expand
  E button "Réduire" @4 - [403,111,47,30] can:invoke
  E button "Agrandir" @5 - [450,111,46,30] can:invoke
  E button "Fermer" @6 - [496,111,47,30] can:invoke
do win.type_text(@0 " Luna verified 18dad1224f88d9a8")
R win.type_text ok 2.6s @r1 +value-is route:WM_SETTEXT focus-kept
D @0 value="initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8"
do win.click(@1) C shows(text:"Applied: initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8")
R win.click ok @r2 +shows route:BM_CLICK focus-kept
D window.2 label="Applied: initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8"
I win.click writes:"T16NativeProbe/Applied text" ui:preview.outline emits:shared-log
