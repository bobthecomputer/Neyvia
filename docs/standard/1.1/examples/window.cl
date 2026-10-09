CL 1.1
-- Windows window layer (T16). Same sources and real Luna run as 1.0 (../../examples/window.cl, ../../examples/today/window.*).
-- The 1.0 run needed 12 MCP calls; here the procedure does set + apply + verify in one call.

-- L0
L win v2 untrusted -- native Windows apps (UIA, background)

-- L1
P win.set_and_apply(field, text, apply) G: text in win.text()
P win.set_field(field, text) G: win.value(field) == text
J right_element "act"|"look_again": "Is this the element the task means?"
A win.windows() -> windows[window title app]
A win.inspect(window, query?) -> tree -- re-binds every e-ref
A win.set_value(field, value) ~
A win.type_text(field, text) ~ -- appends at the caret
A win.click(target) !
A win.press_key(key) !
A win.text() -> str -- all visible text of the window
A win.value(field) -> str
A win.request_app(app, reason) ! -- asks Paul, waits up to 120 s
A win.wait(timeout_ms) -> note -- while Paul holds control
X paused_by_user -> win.wait(), then continue from the new state

-- runtime
win.inspect(window=w1)
R win.inspect ok h1
K user "Paul" did=["set_value","set_value","click"] note="Authorized bounded Luna proof on the disposable native app." -- host: shared preview log
S win w1 "T16 Built Native Probe" app="T16NativeProbe.exe" #7
E window "T16 Built Native Probe"
 E edit "Task input" e0 value="initial agent build cycle Paul checked UI joined agent continued after UI Luna verified"
 E button "Apply" e1
 E text "Applied: initial agent build cycle Paul checked UI joined agent continued after UI Luna verified"
 E titlebar e2 value="T16 Built Native Probe"
  E menubar "Système"
   E menuitem "Système" e3
  E button "Réduire" e4
  E button "Agrandir" e5
  E button "Fermer" e6
run win.set_and_apply(field=e0, text="initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8", apply=e1)
R win.set_and_apply ok r1 +value-is +G
D e0 value="initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8"
D window.2 label="Applied: initial agent build cycle Paul checked UI joined agent continued after UI Luna verified Luna verified 18dad1224f88d9a8"
I win.click wrote="T16NativeProbe: Applied text" route="BM_CLICK" focus="kept" undo=none

-- host
A win.set_value(field:ref value:str) ~ = cua.action(tool=set_value args={element_token=field.token window_id=auto pid=auto})
A win.click(target:ref) ! = cua.action(tool=click args={element_token=target.token window_id=auto pid=auto delivery_mode="background"})
A win.value(field:ref) -> str = cua.inspect(window_id=auto)[field].value
A win.text() -> str = cua.inspect(window_id=auto).tree_markdown
C win.set_value value-is: cua.verify(field, value).status == "satisfied"
P win.set_and_apply(field:ref text:str apply:ref): win.inspect(window=field.window); J right_element="act"; win.set_value(field=field value=text) C value-is; win.click(target=apply)
-- refs re-bind to the newest inspect; element tokens, window_id, pid and sessionId are never shown or written by the agent.
-- ask: the T16 danger-label gate (delete|send|pay|submit|...) appears as R ask + K approval.
