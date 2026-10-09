// Dev-only simulated driver for the computer-use preview: the same shapes as the contract in
// plans/15-handoff.md "## T16" (Session, Frame, LogEntry, focus events, cua ActionResult), with
// two fake Windows apps (Calculator and Notepad) drawn as SVG. A scripted "Codex" checks that
// 12 + 30 = 42, writes it in Notepad, asks before deleting text, then watches what Paul does.
// Loaded only with ?fixtures=1 / ?cua=demo or the dev "Show the demo" button; never in a build path.

const CALC = 101;
const PAD = 102;
const now = () => new Date().toISOString();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const esc = value => String(value).replace(/[&<>"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);

const CALC_KEYS = [["C", "⌫", "%", "÷"], ["7", "8", "9", "×"], ["4", "5", "6", "−"], ["1", "2", "3", "+"], ["±", "0", ".", "="]];
const CALC_SIZE = { w: 320, h: 470 };
const PAD_SIZE = { w: 560, h: 400 };
const BOUNDS = { [CALC]: { x: 1180, y: 160, width: 320, height: 470 }, [PAD]: { x: 560, y: 220, width: 560, height: 400 } };

function calcButtons() {
  const top = 150, pad = 8, gap = 4;
  const w = (CALC_SIZE.w - pad * 2 - gap * 3) / 4;
  const h = (CALC_SIZE.h - top - pad - gap * 4) / 5;
  return CALC_KEYS.flatMap((row, r) => row.map((label, c) => ({ label, x: Math.round(pad + c * (w + gap)), y: Math.round(top + r * (h + gap)), w: Math.round(w), h: Math.round(h) })));
}

const OPS = { "+": (a, b) => a + b, "−": (a, b) => a - b, "×": (a, b) => a * b, "÷": (a, b) => (b === 0 ? NaN : a / b) };
const tidy = value => (Number.isFinite(value) ? String(Math.round(value * 1e10) / 1e10) : "Can't divide by zero");

function pressCalc(calc, label) {
  const value = Number(calc.display) || 0;
  if (/^[0-9]$/.test(label)) return { ...calc, display: calc.fresh || calc.display === "0" ? label : `${calc.display}${label}`.slice(0, 16), fresh: false };
  if (label === ".") return calc.display.includes(".") && !calc.fresh ? calc : { ...calc, display: calc.fresh ? "0." : `${calc.display}.`, fresh: false };
  if (label === "C") return { display: "0", acc: null, op: null, fresh: true, expr: "" };
  if (label === "⌫") return calc.fresh ? calc : { ...calc, display: calc.display.length > 1 ? calc.display.slice(0, -1) : "0" };
  if (label === "±") return { ...calc, display: tidy(-value) };
  if (label === "%") return { ...calc, display: tidy(value / 100) };
  if (OPS[label]) {
    const acc = calc.acc != null && calc.op && !calc.fresh ? OPS[calc.op](calc.acc, value) : value;
    return { display: tidy(acc), acc, op: label, fresh: true, expr: `${tidy(acc)} ${label}` };
  }
  if (label === "=") {
    if (calc.acc == null || !calc.op) return calc;
    const result = OPS[calc.op](calc.acc, value);
    return { display: tidy(result), acc: null, op: null, fresh: true, expr: `${tidy(calc.acc)} ${calc.op} ${tidy(value)} =` };
  }
  return calc;
}

function renderCalc(calc) {
  const buttons = calcButtons().map(button => {
    const equals = button.label === "=";
    const digit = /^[0-9.±]$/.test(button.label);
    return `<rect x="${button.x}" y="${button.y}" width="${button.w}" height="${button.h}" rx="5" fill="${equals ? "#0067c0" : digit ? "#ffffff" : "#f9f9f9"}" stroke="#e5e5e5"/>`
      + `<text x="${button.x + button.w / 2}" y="${button.y + button.h / 2 + 7}" text-anchor="middle" font-size="19" fill="${equals ? "#ffffff" : "#1b1b1b"}">${esc(button.label)}</text>`;
  }).join("");
  const size = calc.display.length > 11 ? 30 : 46;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${CALC_SIZE.w}" height="${CALC_SIZE.h}" font-family="Segoe UI, system-ui, sans-serif">`
    + `<rect width="100%" height="100%" fill="#f3f3f3"/>`
    + `<text x="16" y="21" font-size="12" fill="#1b1b1b">Calculator</text>`
    + `<text x="296" y="21" font-size="12" fill="#5d5d5d">✕</text><text x="262" y="21" font-size="12" fill="#5d5d5d">▢</text><text x="228" y="21" font-size="12" fill="#5d5d5d">—</text>`
    + `<text x="16" y="56" font-size="18" font-weight="600" fill="#1b1b1b">≡  Standard</text>`
    + `<text x="304" y="84" text-anchor="end" font-size="14" fill="#5d5d5d">${esc(calc.expr || "")}</text>`
    + `<text x="304" y="134" text-anchor="end" font-size="${size}" font-weight="600" fill="#1b1b1b">${esc(calc.display)}</text>`
    + buttons + `</svg>`;
}

function wrapLines(text, width = 62) {
  const out = [];
  for (const line of String(text).split("\n")) {
    if (!line) { out.push(""); continue; }
    for (let at = 0; at < line.length; at += width) out.push(line.slice(at, at + width));
  }
  return out;
}

function renderPad(pad) {
  const lines = wrapLines(pad.text);
  const shown = lines.slice(-12);
  const body = shown.map((line, index) => `<text x="14" y="${88 + index * 22}" font-size="15" fill="#1b1b1b" xml:space="preserve">${esc(line)}</text>`).join("");
  const last = shown[shown.length - 1] || "";
  const caretX = 14 + last.length * 8.25;
  const caretY = 72 + Math.max(0, shown.length - 1) * 22;
  const title = `${pad.text ? "*" : ""}Untitled - Notepad`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${PAD_SIZE.w}" height="${PAD_SIZE.h}" font-family="Segoe UI, system-ui, sans-serif">`
    + `<rect width="100%" height="100%" fill="#f3f3f3"/>`
    + `<text x="14" y="21" font-size="12" fill="#1b1b1b">${esc(title)}</text>`
    + `<text x="536" y="21" font-size="12" fill="#5d5d5d">✕</text><text x="502" y="21" font-size="12" fill="#5d5d5d">▢</text><text x="468" y="21" font-size="12" fill="#5d5d5d">—</text>`
    + `<text x="14" y="50" font-size="13" fill="#1b1b1b">File</text><text x="54" y="50" font-size="13" fill="#1b1b1b">Edit</text><text x="94" y="50" font-size="13" fill="#1b1b1b">View</text>`
    + `<rect x="0" y="60" width="${PAD_SIZE.w}" height="316" fill="#ffffff"/>`
    + `<g font-family="Consolas, monospace">${body}</g>`
    + (pad.focused ? `<rect x="${caretX}" y="${caretY}" width="1.5" height="20" fill="#1b1b1b"/>` : "")
    + `<text x="14" y="393" font-size="11" fill="#5d5d5d">Ln ${Math.max(1, lines.length)}, Col ${last.length + 1}</text><text x="546" y="393" text-anchor="end" font-size="11" fill="#5d5d5d">UTF-8</text>`
    + `</svg>`;
}

function calcElements() {
  return [
    { role: "Text", label: "Display", actions: ["text"], box: { x: 8, y: 92, w: 304, h: 52 }, value: true },
    ...calcButtons().map(button => ({ role: "Button", label: button.label, actions: ["invoke"], box: { x: button.x, y: button.y, w: button.w, h: button.h } })),
  ];
}
function padElements() {
  return [
    { role: "MenuItem", label: "File", actions: ["invoke", "expand"], box: { x: 8, y: 36, w: 38, h: 22 } },
    { role: "MenuItem", label: "Edit", actions: ["invoke", "expand"], box: { x: 48, y: 36, w: 40, h: 22 } },
    { role: "MenuItem", label: "View", actions: ["invoke", "expand"], box: { x: 90, y: 36, w: 42, h: 22 } },
    { role: "Edit", label: "Text editor", actions: ["set_value", "text", "scroll"], box: { x: 0, y: 60, w: 560, h: 316 }, value: true },
  ];
}

export function createDemoDriver() {
  let cursor = 0;
  let logSeq = 0;
  let idSeq = 0;
  let run = 0;
  const listeners = new Set();
  let state;

  const reset = () => {
    run += 1;
    state = {
      calc: { display: "0", acc: null, op: null, fresh: true, expr: "" },
      pad: { text: "", focused: false },
      frames: { [CALC]: 1, [PAD]: 1 },
      log: [],
      paulSince: [],
      waiters: new Map(),
      session: {
        id: "s-demo", owner: { chatId: "s-codex-approve", app: "codex", title: "Check the calculator adds right" },
        status: "active", control: "agent", pausedReason: null, foreground: false,
        allow: [{ app: "calc.exe", name: "Calculator", by: "paul" }, { app: "notepad.exe", name: "Notepad", by: "paul" }],
        approvals: [], counts: { agent: 0, paul: 0 }, startedAt: now(), lastActionAt: now(), focusWindow: CALC,
      },
    };
  };
  reset();

  const allowed = process => state.session.allow.some(row => row.app === process);
  const WINDOWS = [
    { window_id: CALC, pid: 4120, app_name: "Calculator", process: "calc.exe", title: "Calculator", size: CALC_SIZE },
    { window_id: PAD, pid: 5232, app_name: "Notepad", process: "notepad.exe", title: "Untitled - Notepad", size: PAD_SIZE },
  ];
  const frameOf = win => {
    const row = WINDOWS.find(item => item.window_id === win);
    return { seq: state.frames[win], windowId: win, captureId: `capture_demo_${win}_${state.frames[win]}`, width: row.size.w, height: row.size.h, scale: 1, at: now(), unavailable: allowed(row.process) ? null : "not_allowed" };
  };
  const snapshot = () => ({
    ...state.session, logSeq,
    windows: WINDOWS.map(row => ({
      window_id: row.window_id, pid: row.pid, app_name: row.app_name, process: row.process,
      title: row.window_id === PAD && state.pad.text ? "*Untitled - Notepad" : row.title,
      bounds: BOUNDS[row.window_id], is_on_screen: true, minimized: false, allowed: allowed(row.process), manual: null, frame: frameOf(row.window_id),
    })),
  });

  const emit = (type, data) => {
    cursor += 1;
    for (const listener of listeners) listener({ cursor, type, sessionId: state.session.id, data });
  };
  const emitSession = () => emit("session", snapshot());
  const bump = win => { state.frames[win] += 1; emit("frame", frameOf(win)); };

  const elementsOf = win => (win === CALC ? calcElements() : padElements()).map((element, index) => ({
    element_index: index, element_token: `s0000${win}:${index}`, role: element.role, label: element.label, depth: 3, enabled: true,
    actions: element.actions, value: element.value ? (win === CALC ? state.calc.display : state.pad.text) : undefined,
    screenshot_frame: element.box, frame: { x: element.box.x + BOUNDS[win].x, y: element.box.y + BOUNDS[win].y, w: element.box.w, h: element.box.h },
  }));
  const hit = (win, x, y) => {
    let best = null;
    for (const element of elementsOf(win)) {
      const box = element.screenshot_frame;
      if (x >= box.x && y >= box.y && x <= box.x + box.w && y <= box.y + box.h && (!best || box.w * box.h < best.screenshot_frame.w * best.screenshot_frame.h)) best = element;
    }
    return best;
  };
  const brief = element => (element ? { token: element.element_token, role: element.role, label: element.label, frame: element.screenshot_frame } : null);

  const addLog = entry => {
    const row = { id: `l-${++idSeq}`, seq: ++logSeq, at: now(), status: "ok", result: null, ms: 0, ...entry };
    state.log.push(row);
    if (row.by === "paul" && row.tool !== "control") state.paulSince.push(row);
    emit("log", row);
    return row;
  };
  const updateLog = (row, patch) => { Object.assign(row, patch); emit("log", row); };
  const note = (text, by = "agent") => addLog({ by, who: by === "agent" ? "Codex" : "You", tool: "note", args: { text }, text });

  const typeInto = (win, text) => {
    if (win === PAD) { state.pad = { ...state.pad, text: `${state.pad.text}${text}`.slice(-4000), focused: true }; return true; }
    let changed = false;
    for (const char of text) {
      const label = { "*": "×", x: "×", "/": "÷", "-": "−", "+": "+", "=": "=", "\n": "=", ",": "." }[char] || char;
      if (/^[0-9.]$/.test(label) || OPS[label] || label === "=") { state.calc = pressCalc(state.calc, label); changed = true; }
    }
    return changed;
  };

  /** One action from the agent or Paul, through the same path (the contract's shared log). */
  async function perform(by, tool, args, win) {
    const session = state.session;
    const who = by === "agent" ? "Codex" : "You";
    const row = WINDOWS.find(item => item.window_id === win);
    if (session.status === "ended") return addLog({ by, who, tool, windowId: win, app: row?.app_name, args, status: "refused", result: { effect: "refused", route: "accessibility", error: { code: "session_ended", hint: "Start a new session." } } });
    if (!row || !allowed(row.process)) return addLog({ by, who, tool, windowId: win, app: row?.app_name, args, status: "refused", result: { effect: "refused", route: "accessibility", error: { code: "app_not_allowed", hint: "Ask Paul to allow the app (request_app)." } } });
    if (by === "agent" && session.control === "paul") return addLog({ by, who, tool, windowId: win, app: row.app_name, args, status: "refused", result: { effect: "refused", route: "accessibility", error: { code: "paused_by_user", hint: "Call preview_wait." } } });
    const element = args.element_token ? elementsOf(win).find(item => item.element_token === args.element_token) : args.x != null ? hit(win, args.x, args.y) : null;
    const point = args.x != null ? { x: args.x, y: args.y } : element ? { x: element.screenshot_frame.x + element.screenshot_frame.w / 2, y: element.screenshot_frame.y + element.screenshot_frame.h / 2 } : null;
    const captureId = frameOf(win).captureId;
    if (by === "agent") {
      emit("focus", { windowId: win, by, tool, phase: "about", element: brief(element), point, captureId });
      await sleep(650);
    }
    const started = performance.now();
    let effect = "unverifiable";
    let evidence = [];
    if (tool === "click" || tool === "double_click") {
      if (win === CALC && element?.role === "Button") {
        state.calc = pressCalc(state.calc, element.label);
        effect = "confirmed";
        evidence = [{ kind: "value_readback", detail: `display read back as ${state.calc.display}` }];
      } else if (win === PAD && element?.label === "Text editor") {
        state.pad = { ...state.pad, focused: true };
        effect = "confirmed";
        evidence = [{ kind: "value_readback", detail: "caret in the text editor" }];
      } else effect = element ? "unverifiable" : "suspected_noop";
    } else if (tool === "type_text") {
      effect = typeInto(win, args.text || "") ? "confirmed" : "suspected_noop";
      if (effect === "confirmed") evidence = [{ kind: "value_readback", detail: win === CALC ? `display read back as ${state.calc.display}` : "text read back" }];
    } else if (tool === "press_key") {
      const key = args.key;
      if (win === PAD && key === "enter") { typeInto(PAD, "\n"); effect = "confirmed"; }
      else if (win === PAD && key === "backspace") { state.pad = { ...state.pad, text: state.pad.text.slice(0, -1) }; effect = "confirmed"; }
      else if (win === PAD && key === "delete" && state.pad.selectAll) { state.pad = { text: "", focused: true }; effect = "confirmed"; }
      else if (win === CALC && ["enter", "backspace", "escape", "delete"].includes(key)) {
        state.calc = pressCalc(state.calc, { enter: "=", backspace: "⌫", escape: "C", delete: "C" }[key]);
        effect = "confirmed";
      } else effect = "suspected_noop";
    } else if (tool === "hotkey") {
      if (win === PAD && (args.keys || []).join("+") === "ctrl+a") { state.pad = { ...state.pad, selectAll: true }; effect = "unverifiable"; }
      else effect = "suspected_noop";
    } else if (tool === "scroll" || tool === "drag" || tool === "right_click") effect = "suspected_noop";
    if (tool !== "hotkey" && win === PAD) state.pad = { ...state.pad, selectAll: tool === "press_key" && args.key === "delete" ? false : state.pad.selectAll };
    session.counts[by === "agent" ? "agent" : "paul"] += 1;
    session.lastActionAt = now();
    session.focusWindow = win;
    const entry = addLog({
      by, who, tool, windowId: win, app: row.app_name, element: brief(element), args, captureId,
      ms: Math.round(performance.now() - started) + (by === "paul" ? 40 : 90),
      result: { effect, route: "accessibility", delivery: { mode: args.delivery_mode || "background" }, evidence, summary: "" },
    });
    bump(win);
    emit("focus", { windowId: win, by, tool, phase: "done", element: brief(element), point, captureId: frameOf(win).captureId });
    return entry;
  }

  /** An agent action that needs Paul's yes first (the contract's irreversible-action approval). */
  function ask(kind, tool, win, summary, element) {
    const id = `a-${++idSeq}`;
    const approval = { id, kind, tool, summary, app: WINDOWS.find(row => row.window_id === win)?.process, element: brief(element), at: now(), expiresAt: new Date(Date.now() + 120000).toISOString() };
    state.session.approvals = [...state.session.approvals, approval];
    const entry = addLog({ by: "agent", who: "Codex", tool: "approval", windowId: win, app: WINDOWS.find(row => row.window_id === win)?.app_name, element: brief(element), args: { summary }, status: "pending_approval", text: summary, approvalId: id });
    emitSession();
    return new Promise(resolve => state.waiters.set(id, decision => {
      updateLog(entry, { status: decision === "allow" ? "ok" : "denied" });
      resolve(decision === "allow");
    }));
  }

  // The scripted agent: waits while Paul has control, reacts to what Paul does.
  const token = label => elementsOf(CALC).find(element => element.label === label)?.element_token;
  async function waitTurn(myRun) {
    while (myRun === run && (state.session.control === "paul" || state.session.status !== "active")) await sleep(300);
    return myRun === run;
  }
  async function agentScript() {
    const myRun = run;
    const step = async fn => { await sleep(900); if (!(await waitTurn(myRun))) throw new Error("reset"); return fn(); };
    try {
      await step(() => note("Checking that the calculator adds 12 + 30 right. Driving it in the background."));
      for (const label of ["C", "1", "2", "+", "3", "0", "="]) await step(() => perform("agent", "click", { element_token: token(label) }, CALC));
      await step(() => note(`Display shows ${state.calc.display}. Writing the result in Notepad.`));
      await step(() => perform("agent", "click", { element_token: `s0000${PAD}:3` }, PAD));
      await step(() => perform("agent", "type_text", { text: `12 + 30 = ${state.calc.display} (draft)` }, PAD));
      await step(() => perform("agent", "hotkey", { keys: ["ctrl", "a"] }, PAD));
      const ok = await step(() => ask("action", "press_key", PAD, "Press Delete to remove all the text in Notepad", elementsOf(PAD)[3]));
      if (ok) {
        await step(() => perform("agent", "press_key", { key: "delete" }, PAD));
        await step(() => perform("agent", "type_text", { text: "12 + 30 = 42, checked in Calculator." }, PAD));
      } else await step(() => note("Okay, I left the draft text as it is."));
      await step(() => note("Done. Try the calculator yourself; I'll see what you do."));
      state.paulSince = [];
      // Watching: react to Paul's actions and to a give-back note.
      while (myRun === run && state.session.status === "active") {
        await sleep(1200);
        if (!(await waitTurn(myRun))) return;
        if (state.handback) {
          const text = state.handback.note;
          state.handback = null;
          await step(() => note(text ? `Got it: "${text}". Looking again.` : "Thanks, I have control again. Looking again."));
          await step(() => perform("agent", "click", { element_token: token("=") }, CALC));
          await step(() => note(`Calculator shows ${state.calc.display}.`));
        }
        const pressedEquals = state.paulSince.some(row => row.windowId === CALC && (row.element?.label === "=" || row.args?.key === "enter" || /=/.test(row.args?.text || "")));
        if (pressedEquals) {
          const count = state.paulSince.length;
          state.paulSince = [];
          await step(() => note(`I saw your ${count} action${count === 1 ? "" : "s"} in Calculator: it shows ${state.calc.display}.`));
        }
      }
    } catch { /* the demo was reset or ended */ }
  }

  setTimeout(() => void agentScript(), 400);

  const sessionOf = args => {
    if (args.sessionId && args.sessionId !== state.session.id) throw Object.assign(new Error("No such session"), { code: "unknown_session" });
    return state.session;
  };

  return {
    demo: true,
    async state() {
      return { driver: { available: true, name: "Demo driver (simulated)", version: "fixture", platform: "windows" }, sessions: [snapshot()] };
    },
    frameUrl(sessionId, windowId) {
      const svg = Number(windowId) === CALC ? renderCalc(state.calc) : renderPad(state.pad);
      return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    },
    subscribe(sessionId, { onEvent, onState }) {
      listeners.add(onEvent);
      onState?.("live");
      onEvent({ cursor, type: "session", sessionId: state.session.id, data: snapshot() });
      for (const row of state.log.slice(-200)) onEvent({ cursor, type: "log", sessionId: state.session.id, data: row });
      return () => listeners.delete(onEvent);
    },
    async call(op, args = {}) {
      await sleep(60);
      switch (op) {
        case "open": {
          if (state.session.status === "ended") { reset(); setTimeout(() => void agentScript(), 400); }
          for (const app of args.apps || []) if (!allowed(app)) state.session.allow.push({ app, name: app.replace(/\.exe$/i, ""), by: "paul" });
          emitSession();
          return snapshot();
        }
        case "snapshot": {
          sessionOf(args);
          const win = Number(args.windowId);
          const frame = frameOf(win);
          const row = WINDOWS.find(item => item.window_id === win);
          const elements = elementsOf(win);
          return { pid: row.pid, window_id: win, app_name: row.app_name, window_title: row.title, capture_id: frame.captureId, screenshot_width: frame.width, screenshot_height: frame.height, element_count: elements.length, elements };
        }
        case "input": {
          sessionOf(args);
          const { kind, windowId, captureId: _capture, sessionId: _session, ...rest } = args;
          return perform("paul", kind, rest, Number(windowId));
        }
        case "control": {
          const session = sessionOf(args);
          session.control = args.mode === "paul" ? "paul" : "agent";
          session.pausedReason = session.control === "paul" ? "take_over" : null;
          if (session.control === "agent") state.handback = { note: String(args.note || "").trim() };
          addLog({ by: "paul", who: "You", tool: "control", args: { mode: session.control, note: args.note || "" },
            text: session.control === "paul" ? "You took over. Codex is paused." : `You gave control back${args.note ? `: "${args.note}"` : "."}` });
          emitSession();
          return snapshot();
        }
        case "allow": {
          const session = sessionOf(args);
          if (args.allowed) { if (!allowed(args.app)) session.allow.push({ app: args.app, name: args.name || args.app.replace(/\.exe$/i, ""), by: "paul" }); }
          else session.allow = session.allow.filter(row => row.app !== args.app);
          addLog({ by: "paul", who: "You", tool: "allow", args: { app: args.app, allowed: Boolean(args.allowed) }, text: `${args.allowed ? "Allowed" : "Removed"} ${args.name || args.app}` });
          for (const win of [CALC, PAD]) bump(win);
          emitSession();
          return snapshot();
        }
        case "foreground": {
          const session = sessionOf(args);
          session.foreground = Boolean(args.allowed);
          emitSession();
          return snapshot();
        }
        case "approve": {
          const session = sessionOf(args);
          const waiter = state.waiters.get(args.approvalId);
          session.approvals = session.approvals.filter(row => row.id !== args.approvalId);
          state.waiters.delete(args.approvalId);
          waiter?.(args.decision);
          emitSession();
          return snapshot();
        }
        case "apps":
          return { apps: [
            { name: "Calculator", process: "calc.exe", pid: 4120 }, { name: "Notepad", process: "notepad.exe", pid: 5232 },
            { name: "File Explorer", process: "explorer.exe", pid: 812 }, { name: "Paint", process: "mspaint.exe", pid: 9044 },
          ] };
        case "end": {
          const session = sessionOf(args);
          session.status = "ended";
          for (const waiter of state.waiters.values()) waiter("deny");
          state.waiters.clear();
          session.approvals = [];
          addLog({ by: "paul", who: "You", tool: "control", args: {}, text: "You ended the session." });
          emitSession();
          return snapshot();
        }
        default:
          throw new Error(`Unknown op: ${op}`);
      }
    },
  };
}
