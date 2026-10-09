# browser (user side)

UI chapter for the integrated browser (plan 15 T20, Search + Obscura). The bot side and the engines are in
`manuals/browser.manual.json` (generated view: `docs/manuals/browser.md`); this file uses the same section
names, one line per fact, naming the real call for each action and check, so it folds into that manual
mechanically. Code: `web/src/neyvia/next/NxBrowser.jsx`, `NxBrowserParts.jsx`, `nxBrowserApi.js`,
`nxBrowserModel.js`, `NxBrowserPip.jsx`, `nxBrowser.css`.

## overview
INDEX Browser app: Paul's visible tabs (WebView2, desktop app) and agents' headless tabs (Obscura) in one list, with spaces, command bar, split view, peek, reader mode, picture in picture and "what the agent sees".
OPEN launcher "Browser" (Ctrl Space), `os.openApp("browser", "", <url>?)`, or "Open in Browser" on a `pane.show {kind:"browser"}` page. A target URL opens in a tab, reusing an open tab with the same address.
TRANSPORT every user action is `browser_call_command {op, args}` (web: POST /api/backend as the owner; desktop: `call_desktop_backend_command`). Same state as `neyvia.browser.*`.
STATE poll: GET-equivalent `browser_call_command {op:"state"}` every 2.5 s, every 0.7 s while a tab loads, a native action is pending or the agent view is open; paused while the window is hidden.
APPSTATE the screen reports `{space, activeTabId, reader, split, peek, tabsPlacement, pip}` through `reportAppState("browser", …)` (POST /api/ui/app-state) so the bot side knows what Paul is looking at.

## state observers
OBSERVE tabs: `state.tabs[]` {id, spaceId, profileId, url, title, pinned, engine webview2|obscura, live, loading, status, agentGranted}. One word per tab from `tabStatus`: Loading, Sleeping (suspended, lazy restore), On your PC (runtime not attached here), Waiting for you (agent tab not granted, gold), Agent (granted agent tab), Agent can act (visible tab granted, gold), Moving to a visible tab (promoting), Couldn't load.
OBSERVE spaces: `state.spaces[]` {id, name, profileId}; the active space is per viewer (`local nx.browser.space`), the last tab per space is remembered (`nx.browser.last.<space>`).
OBSERVE runtime: `state.runtime.connected` (desktop WebView2 runtime polling), `state.headless` {connected, stealth:false, automationUserAgent}, `state.laya` {available, status}.
OBSERVE agent page: the Obscura tab's viewport shows its fresh DOM projection every 2 s (`op:"observe", cached:true`; the backend re-reads headless tabs), fields with values, headings, buttons, links and text; a field whose value changed since the last read is marked "Just changed".
OBSERVE what the agent sees: `neyvia.perception.observe {layer:"browser", source:{tabId}}` then `perception.project` for large pages; shows the controls list (id, role, name, value, actions), characters and token estimate, Readable/Exact.
OBSERVE history/downloads: `state.history[]` feeds the address autocomplete and the command bar; `state.downloads[]` lists status, size and path.

## typed actions
ACTION open tab: command bar (Ctrl T, "New tab") or address field Alt Enter -> `tab.open {url, spaceId}`; text without a scheme is an address when it looks like a host (`example.com`, `localhost:5173`) else a DuckDuckGo search; `javascript:`, `file:` and URLs with credentials are refused in the UI before any call.
ACTION navigate: address field Enter -> `tab.navigate {tabId, url}` on the active visible tab (an agent tab never gets Paul's navigation; a new tab opens instead).
ACTION back/forward/reload: toolbar or Alt Left / Alt Right -> `tab.back|tab.forward|tab.reload {tabId}`.
ACTION switch tab: list row, top chip, autocomplete "Switch to tab", command bar -> `tab.activate {tabId}` (wakes a sleeping tab).
ACTION close tab: X on the row or Ctrl W -> `tab.close {tabId}`.
ACTION pin: menu "Pin tab" -> `tab.update {tabId, pinned}`; pinned tabs show as tiles above the list.
ACTION split view: toolbar button or command bar -> `split {left: active, right: last other tab}`; close -> `split {left:null,right:null}`.
ACTION peek: command bar Shift Enter on an address or history row -> `tab.open`, `peek {tabId}`, `tab.activate {previous}`; "Open as a tab" -> `peek {tabId:null}` + `tab.activate`; X -> `peek {tabId:null}` + `tab.close`.
ACTION new space: "+" in the space bar -> `space.create {name, profileId}`; "Separate sign-ins" first runs `profile.create {name}` (own cookies and storage).
ACTION grant/revoke agents: agent tab "Let it act" / "Pause the agent", menu "Let agents act in this tab", gold chip "Agent can act · Stop" -> `tab.grant {tabId, enabled}` (owner only).
ACTION watch an agent tab: "Watch in a visible tab" -> `promote {tabId}` (wait for native completion via `action.get`), `tab.activate`, then `tab.grant {enabled:true}` so the agent continues in the visible WebView2 tab.
ACTION take over: "Take over" -> `promote {tabId}` + `tab.activate`; the grant stays off (promotion revokes it), Paul drives.
ACTION agent engine: sidebar button or menu -> `headless.start` / `headless.stop` (owner; needs NEYVIA_OBSCURA_EXE on the PC service).
ACTION give an agent a task: "Give an agent a task" -> new chat with a drafted prompt naming `neyvia.browser.open` engine "obscura".
ACTION reader mode: book button or command bar -> fresh projection (`observe`; visible tabs wait for `action.get`) rendered as title, headings and paragraphs (`readerFrom`).
ACTION picture in picture: menu or command bar (desktop app) -> the tab floats in a 360x236 frame at the bottom right of Neyvia while the rest of the app is used; "Back to the tab" reopens the Browser.
ACTION tabs placement: "Tabs on top" / "Tabs on the side" (per viewer, `nx.browser.tabs`).

## native layout (desktop app)
LAYOUT the desktop UI attaches the runtime once: `runtime.connect` -> `invoke("browser_runtime_start", {baseUrl, token})` (token memory only; on "Stop the previous browser runtime" it calls `browser_runtime_stop` and attaches again).
LAYOUT each place a page is drawn (main view, split halves, peek card, PiP frame) is measured with a ResizeObserver and reported as `layout {tabs:[{tabId,x,y,width,height,visible}]}` in window CSS pixels; every other live visible tab is sent hidden; identical plans are not resent.
LAYOUT native views draw above the interface: while the command bar, address suggestions, menus or popovers are open every view is hidden (`coverNative`), and leaving the Browser hides them all except the PiP tab.
LAYOUT only the desktop app sends layout; a browser or phone never moves the PC's native views.

## executable checks
CHECK tab opened: `neyvia.browser.state {}` contains a tab with the URL, then `live:true` once native open is acknowledged.
CHECK promoted: after "Watch", the same tabId has `engine:"webview2"`, `live:true`, and `agentGranted:true` (Watch) or `false` (Take over).
CHECK grant: `tab.grant` result `tab.agentGranted` equals the toggle.
CHECK layout: `action.get {actionId}` of the queued layout is `done` with `result.laidOut:true`.
CHECK address parser: `node --test web/src/neyvia/next/nxBrowserModel.test.js` (addresses, searches, refused schemes, autocomplete ranking, reader extraction, layout plan).

## procedures
PROCEDURE agent-task-to-visible-tab: owner starts the engine -> agent `neyvia.browser.open {url, engine:"obscura"}` -> tab appears under Agent tabs, "Waiting for you" -> Paul "Let it act" -> agent observe/action (fields show "Just changed") -> Paul "Watch in a visible tab" -> same tab is a WebView2 page with cookies, localStorage and non-secret form values -> agent continues (granted) or Paul takes over.
PROCEDURE read-later: open page -> reader mode -> back to the page with the same button.
PROCEDURE compare: open two tabs -> split view -> click a half to make it active (the address field follows it).

## judgement points
JUDGE watch-or-take-over: watch when the agent should finish while Paul looks; take over when the page needs Paul's own input (sign-in, payment, a choice).
JUDGE separate-sign-ins: a new space shares the current profile's cookies unless "Separate sign-ins" is ticked.

## pitfalls
PITFALL Pages look blank in a browser or on the phone -> pages are drawn only by the Neyvia desktop app; the screen says so and offers reader mode when the desktop runtime is attached.
PITFALL A menu opens over the page and the page disappears -> intended: native views hide under overlays and come back when the overlay closes.
PITFALL Agent action refused tab_not_granted -> the owner has not granted the tab; the row shows "Waiting for you".
PITFALL Agent action refused after Paul typed in the page -> real input pauses the agent (user_input revokes the grant); grant again to give it back.
PITFALL Watch is disabled -> visible tabs need the desktop runtime attached here.

## frontier
FRONTIER Tracker blocking in visible tabs: not implemented (needs request filtering in the native runtime); agent tabs already block every cross-origin request. The shield popover says so.
FRONTIER Private tabs (no history, profile deleted on close): needs a backend ephemeral profile and history opt-out; shown as "coming" in the menu.
FRONTIER Video picture in picture (the page's own video element): needs page script execution; the tab-level PiP frame is what exists.
FRONTIER LAYA quick judgements: `browser.decide` answers awaiting_provider until the T15 provider is installed in the PC service; the agent view shows "not connected yet".
FRONTIER Favicons: not in the state; tabs show the site's initial.
FRONTIER Vault/password import and Chrome extensions from Search are not built.
FRONTIER The packaged desktop app's UI page needs the PC service's loopback URL for `browser_runtime_start`; dev pages on loopback use their own origin, a `tauri://` page needs `VITE_FLUXIO_BACKEND_URL` or the runtime.connect answer to carry it.
