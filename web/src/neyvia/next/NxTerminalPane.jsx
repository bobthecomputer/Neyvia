import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronRight, Plus, SquareTerminal, TriangleAlert, X } from "lucide-react";

import { nameOf } from "./nxDocsApi.js";
import { PaneMessage } from "./NxFilePane.jsx";
import { panesCall, terminalStreamUrl } from "./nxPanesApi.js";
import { Button, Icon, IconButton, Spinner } from "./nxPrimitives.jsx";
import { useOs } from "./nxOsStore.js";
import { useShownTheme } from "./nxSun.js";
import { PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import "./vendor/xterm/xterm.css";
import "./nxPanes.css";

// pane.show {kind: "terminal"}: a real shell on this PC (ConPTY through the
// backend), in the chat's folder or the folder named by the target. A target
// that is a command is typed on the prompt line, never run: Paul presses
// Enter. Terminals outlive the pane; reopening the same target reattaches and
// replays what the terminal showed. Models read them with neyvia.terminal.read.

const ATTACH_KEY = "nx.term.attach";
const opening = new Map(); // target key -> in-flight open, so a double mount opens one shell

function attachments() {
  try { return JSON.parse(sessionStorage.getItem(ATTACH_KEY) || "{}") || {}; } catch { return {}; }
}
function remember(key, id) {
  try { sessionStorage.setItem(ATTACH_KEY, JSON.stringify({ ...attachments(), [key]: id })); } catch { /* best effort */ }
}

function ensureTerminal(key, args) {
  if (!opening.has(key)) {
    const started = (async () => {
      const { terminals = [] } = await panesCall("terminal.list", {});
      const known = terminals.find(row => row.id === attachments()[key] && row.alive);
      if (known) return known;
      const created = await panesCall("terminal.open", args);
      remember(key, created.id);
      return created;
    })().finally(() => setTimeout(() => opening.delete(key), 1500));
    opening.set(key, started);
  }
  return opening.get(key);
}

function themeFrom(element) {
  const style = getComputedStyle(element);
  const pick = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
  return {
    background: pick("--nx-panel", "#0f1612"),
    foreground: pick("--nx-text", "#f1ede3"),
    // Everything from the window's skin tokens (the code skin's caret, selection and ANSI set).
    cursor: pick("--nx-accent-hi", "#5ec189"),
    cursorAccent: pick("--nx-panel", "#0f1612"),
    selectionBackground: pick("--nx-selection", "rgba(94,193,137,0.3)"),
    selectionInactiveBackground: pick("--nx-active", "rgba(241,237,227,0.09)"),
    scrollbarSliderBackground: pick("--nx-scrollbar", "rgba(241,237,227,0.18)"),
    // The 16 terminal colours come from the code skin (nxAppSkinModel); xterm's own set otherwise.
    ...Object.fromEntries(ANSI_NAMES.map(name => [name, style.getPropertyValue(`--nx-ansi-${name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)}`).trim()]).filter(([, value]) => value)),
  };
}

const ANSI_NAMES = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white", "brightBlack", "brightRed", "brightGreen", "brightYellow", "brightBlue", "brightMagenta", "brightCyan", "brightWhite"];

// The prompt the shell is about to print, drawn until its first bytes arrive, so a new terminal
// opens on a prompt line instead of a lone cursor (it is the same text the shell then writes).
export function promptFor(shell, cwd) {
  const kind = String(shell || "").toLowerCase();
  const where = String(cwd || "").replace(/[\\/]+$/, "") || "~";
  if (/pwsh|powershell/.test(kind)) return `PS ${where}> `;
  if (/cmd/.test(kind)) return `${where}>`;
  const unix = where.replace(/\\/g, "/").replace(/^[A-Za-z]:\/Users\/[^/]+/i, "~");
  return `${unix} $ `;
}

/** Tab names: the folder's name, numbered when two terminals share it ("app", "app (2)"). */
export function tabNames(rows) {
  const seen = new Map();
  return rows.map(row => {
    const base = nameOf(row.cwd) || row.cwd || "Terminal";
    const count = (seen.get(base) || 0) + 1;
    seen.set(base, count);
    return count > 1 ? `${base} (${count})` : base;
  });
}

/** A path as segments for the header: the drive or ~ first, the folder you're in last. */
function segments(cwd) {
  const parts = String(cwd || "").split(/[\\/]+/).filter(Boolean);
  return parts.length > 4 ? [parts[0], "…", ...parts.slice(-2)] : parts;
}

const STATUS_WORDS = { connecting: "Starting", live: "Ready", reconnecting: "Reconnecting…", ended: "Ended" };

let xtermModules = null;
const loadXterm = () => (xtermModules ||= Promise.all([import("./vendor/xterm/xterm.mjs"), import("./vendor/xterm/addon-fit.mjs")]));

/** The text a terminal shows: its buffer, line by line, without trailing blanks. */
function bufferText(term) {
  const buffer = term?.buffer?.active;
  if (!buffer) return "";
  const lines = [];
  for (let index = 0; index < buffer.length; index += 1) lines.push(buffer.getLine(index)?.translateToString(true) ?? "");
  while (lines.length && !lines[lines.length - 1]) lines.pop();
  return lines.join("\n");
}

function Screen({ terminal, onEnded, onChanged }) {
  const host = useRef(null);
  const observation = usePaneObservation();
  const theme = useShownTheme();
  const xterm = useRef(null);
  const readOnly = useRef(false);
  readOnly.current = Boolean(terminal.readonly && !terminal.takeover);
  const [status, setStatus] = useState("connecting");
  const [spoke, setSpoke] = useState(false); // the shell has written something

  useEffect(() => {
    let disposed = false;
    let source = null;
    let retry = 0;
    let timer = 0;
    let cursor = 0;
    let queue = "";
    let sending = Promise.resolve();
    let flushTimer = 0;
    let resizeTimer = 0;
    let observer = null;
    let seen = null;
    let frame = 0;
    let resize = null;
    let term = null;
    let reportTimer = 0;
    // Observation: this terminal's id and the buffer it displays, after the stream is live.
    const reportSoon = () => {
      clearTimeout(reportTimer);
      reportTimer = setTimeout(() => { if (!disposed && term) void observation.report({ runtimeId: `terminal:${terminal.id}`, content: `${terminal.cwd || ""}\n${bufferText(term)}` }); }, 300);
    };

    const send = () => {
      flushTimer = 0;
      const data = queue;
      queue = "";
      if (!data) return;
      sending = sending.then(() => panesCall("terminal.input", { id: terminal.id, data })).catch(() => setStatus("ended"));
    };
    const connect = () => {
      if (disposed) return;
      source = new EventSource(terminalStreamUrl(terminal.id, cursor), { withCredentials: true });
      source.onopen = () => { retry = 0; setStatus("live"); reportSoon(); };
      source.onmessage = frame => {
        let message;
        try { message = JSON.parse(frame.data); } catch { return; }
        if (message.reset) term.reset();
        if (message.data) { term.write(message.data, reportSoon); setSpoke(true); }
        if (typeof message.cursor === "number") cursor = message.cursor;
        if (message.ended) {
          term.write(`\r\n\x1b[2m[The shell ended${message.exitCode != null ? ` with code ${message.exitCode}` : ""}.]\x1b[0m\r\n`);
          setStatus("ended");
          source.close();
          onEnded?.(terminal.id);
        }
      };
      source.onerror = () => {
        source?.close();
        if (disposed) return;
        setStatus("reconnecting");
        // A closed terminal answers 400; after a few tries say it ended.
        if (retry > 4) { setStatus("ended"); return; }
        timer = setTimeout(connect, Math.min(8000, 500 * 2 ** retry++));
      };
    };

    void loadXterm().then(([{ Terminal }, { FitAddon }]) => {
      if (disposed || !host.current) return;
      term = new Terminal({
        fontFamily: getComputedStyle(host.current).getPropertyValue("--nx-mono").trim() || "Cascadia Code, monospace",
        fontSize: parseFloat(getComputedStyle(host.current).fontSize), lineHeight: 1.2, cursorBlink: true, scrollback: 5000, allowProposedApi: false,
        theme: themeFrom(host.current), convertEol: false,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(host.current);
      xterm.current = term;
      // Refit on every size change of the pane (placement moves, the floating side panel, a bubble
      // peek, phone), at most once a frame. Fitting only changes the grid inside the host, never
      // the host's own size, so it can't feed back into the observer. The shell hears the new
      // size only when cols/rows really changed.
      let sent = "";
      const refit = () => {
        frame = 0;
        const box = host.current;
        if (disposed || !box || !box.clientWidth || !box.clientHeight) return; // hidden or collapsed: keep the last size
        try { fit.fit(); } catch { return; }
        box.dataset.cols = String(term.cols);
        box.dataset.rows = String(term.rows);
        const size = `${term.cols}x${term.rows}`;
        if (size === sent) return;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          sent = size;
          void panesCall("terminal.resize", { id: terminal.id, cols: term.cols, rows: term.rows }).catch(() => { sent = ""; });
        }, 120);
      };
      resize = () => { if (!frame) frame = requestAnimationFrame(refit); };
      refit();
      observer = new ResizeObserver(resize);
      observer.observe(host.current);
      // A window that comes back into view (bubble peek, a tab shown again) or a late web font.
      if (typeof IntersectionObserver === "function") {
        seen = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) resize(); });
        seen.observe(host.current);
      }
      document.addEventListener("visibilitychange", resize);
      void document.fonts?.ready.then(resize);
      term.onData(data => {
        if (readOnly.current) return; // a Claude Code view is read-only until the person presses Take over
        queue += data;
        if (!flushTimer) flushTimer = setTimeout(send, 8);
      });
      term.focus();
      connect();
    });
    return () => {
      disposed = true;
      clearTimeout(timer); clearTimeout(flushTimer); clearTimeout(resizeTimer); clearTimeout(reportTimer);
      cancelAnimationFrame(frame);
      observer?.disconnect();
      seen?.disconnect();
      if (resize) document.removeEventListener("visibilitychange", resize);
      source?.close();
      term?.dispose();
      xterm.current = null;
    };
  }, [terminal.id, onEnded, observation]); // eslint-disable-line react-hooks/exhaustive-deps

  // Another terminal took this one's place, or the pane closed: its buffer isn't shown any more.
  useEffect(() => () => observation.withdraw(), [observation]);

  useEffect(() => {
    // Theme changes repaint the terminal in the new colours.
    const id = requestAnimationFrame(() => { if (xterm.current && host.current) xterm.current.options.theme = themeFrom(host.current); });
    return () => cancelAnimationFrame(id);
  }, [theme]);

  const takeOver = async on => {
    try { await panesCall("terminal.takeover", { id: terminal.id, on }); onChanged?.(); xterm.current?.focus(); } catch { /* the view ended */ }
  };
  const parts = segments(terminal.cwd);
  return (
    <>
      <div className="nx-tp-head">
        <span className={`nx-tp-dot is-${status}`} aria-hidden="true" />
        <span className="nx-tp-status" role="status">{STATUS_WORDS[status] || status}</span>
        <ol className="nx-tp-path" aria-label="Folder" title={terminal.cwd}>
          {parts.map((part, index) => (
            <li key={`${index}:${part}`} className={index === parts.length - 1 ? "is-here" : ""}>
              {index ? <Icon as={ChevronRight} size={11} /> : null}<span>{part}</span>
            </li>
          ))}
        </ol>
        <span className="nx-head-spacer" />
        {terminal.claude && status !== "ended" ? (
          terminal.takeover
            ? <Button size="sm" variant="ghost" onClick={() => void takeOver(false)}>Give back</Button>
            : <><span className="nx-tp-shell">Read-only</span><Button size="sm" onClick={() => void takeOver(true)}>Take over</Button></>
        ) : null}
        {terminal.shell && !terminal.claude ? <span className="nx-tp-shell">{terminal.shell}</span> : null}
      </div>
      <div className={`nx-tp-screen${!spoke && status !== "ended" ? " is-waiting" : ""}`} onClick={() => xterm.current?.focus()}>
        <div ref={host} className="nx-tp-host" />
        {!spoke && status !== "ended" ? (
          <div className="nx-tp-ghost" aria-hidden="true"><span>{promptFor(terminal.shell, terminal.cwd)}</span><i /></div>
        ) : null}
        {status === "reconnecting" ? <div className="nx-tp-state">Reconnecting…</div> : null}
      </div>
    </>
  );
}

export function NxTerminalPane({ target, session }) {
  const key = String(target || "") || `workspace:${session?.cwd || ""}`;
  const [state, setState] = useState({ status: "loading", terminals: [], active: null });
  const [attempt, setAttempt] = useState(0);

  const refresh = useCallback(async active => {
    const { terminals = [] } = await panesCall("terminal.list", {});
    setState(current => ({ ...current, status: "ready", terminals, active: active ?? current.active }));
  }, []);

  useEffect(() => {
    let live = true;
    setState(current => ({ ...current, status: "loading" }));
    if (String(target || "").startsWith("claude:")) {
      // A running Claude Code turn: it already has its own terminal in the list, read-only until Take over.
      refresh(String(target)).catch(error => { if (live) setState(current => ({ ...current, status: "error", error: error.message })); });
      return () => { live = false; };
    }
    ensureTerminal(key, { target: target || "", cwd: session?.cwd || "", cols: 100, rows: 30 })
      .then(async created => { if (live) await refresh(created.id); })
      .catch(error => { if (live) setState(current => ({ ...current, status: "error", error: error.message })); });
    return () => { live = false; };
  }, [key, target, session?.cwd, refresh, attempt]);

  const active = state.terminals.find(row => row.id === state.active);
  const names = tabNames(state.terminals);
  const openAnother = async () => {
    try {
      const created = await panesCall("terminal.open", { cwd: active?.cwd || session?.cwd || "", cols: 100, rows: 30 });
      await refresh(created.id);
    } catch (error) { setState(current => ({ ...current, error: error.message })); }
  };
  const close = async id => {
    await panesCall("terminal.close", { id }).catch(() => {});
    const { terminals = [] } = await panesCall("terminal.list", {});
    setState(current => ({ ...current, terminals, active: current.active === id ? terminals[terminals.length - 1]?.id || null : current.active }));
  };
  const onEnded = useCallback(() => { void refresh(); }, [refresh]);

  if (state.status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (state.status === "error") {
    return <PaneMessage icon={TriangleAlert} title="The terminal can't start" action={<Button size="sm" onClick={() => setAttempt(value => value + 1)}>Try again</Button>}><PaneRefused reason={state.error} />{state.error}</PaneMessage>;
  }
  return (
    <div className="nx-tp">
      <div className="nx-tp-tabs" role="tablist" aria-label="Terminals">
        {state.terminals.map((row, index) => (
          <div key={row.id} className={`nx-tp-tab${row.id === state.active ? " is-on" : ""}${row.alive ? "" : " is-ended"}`}>
            <button type="button" role="tab" aria-selected={row.id === state.active} title={[row.cwd, row.shell].filter(Boolean).join(" · ")}
              onClick={() => setState(current => ({ ...current, active: row.id }))}>
              <Icon as={SquareTerminal} size={13} />
              <span>{row.claude ? `Claude · ${names[index]}` : names[index]}</span>
            </button>
            <IconButton size="sm" icon={X} label={row.alive ? "End this terminal" : "Remove"} onClick={() => void close(row.id)} />
          </div>
        ))}
        <IconButton size="sm" icon={Plus} label="New terminal" onClick={() => void openAnother()} />
        <span className="nx-head-spacer" />
        {active?.typed ? (
          <span className="nx-tp-hint" title={active.typed}>Typed for you, not run: <code>{active.typed}</code></span>
        ) : null}
      </div>
      {active ? <Screen key={active.id} terminal={active} onEnded={onEnded} onChanged={() => void refresh()} /> : (
        <PaneMessage icon={SquareTerminal} title="No terminal open" action={<Button size="sm" icon={Plus} onClick={() => void openAnother()}>New terminal</Button>} />
      )}
    </div>
  );
}
