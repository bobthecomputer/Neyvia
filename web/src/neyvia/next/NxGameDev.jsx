import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box, Boxes, Copy, ExternalLink, FileCheck2, FileCode2, Gamepad2, ListTree, Play, RefreshCw, ScrollText, CircleStop,
  TriangleAlert, Wrench,
} from "lucide-react";

import "./nxGameDev.css";
import { useReceipts } from "./useGameDevReceipts.js";
import { reportAppState } from "./nxBus.js";
import { backendBase, callNx } from "./nxApi.js";
import { Button, Icon, IconButton, Spinner, StatusDot, ago, local, useTick } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { useShownTheme } from "./nxSun.js";
import { THEME_SCHEME } from "./nxThemeRegistry.js";
import {
  ACTION_WORDS, ENGINE_TABS, actionFields, buildArgs, engineState, formatVector, friendlyError, initialValues, isDone,
  folderName, keepSelection, latestTree, newRequestId, receiptState, sessionLabel, sessionState, shortPath, sortSessions, tabForStage,
  visibleFields,
} from "./nxGameDevModel.js";

// Game Dev suite (07 §8, T12): one screen for every editor bridge. Each tab
// shows the editor's real bridge state and setup, the exact session Paul
// picks, its actions and their receipts. Every button calls the same
// gamedev_*_command the model reaches through neyvia.gamedev.*.

const TAB_ICONS = { babylon: Boxes, godot: Gamepad2, unity: Box, roblox: Gamepad2, blender: Box, assets: FileCheck2 };
const NO_FORM = new Set(["run", "stop", "console", "reload", "inspect"]);
const seenAt = value => (value ? new Date(Number(value) * 1000).toISOString() : "");
const pretty = value => { try { return JSON.stringify(value, null, 2); } catch { return String(value); } };
const copy = text => navigator.clipboard?.writeText(text).then(() => os.notify({ level: "info", message: "Copied" }), () => {});

// ------------------------------------------------------------ receipts

// ------------------------------------------------------------ app

export function NxGameDev({ app, target }) {
  const [tab, setTab] = useState(() => tabForStage(app, target));
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(() => local.get("gamedev.picked", {}));
  const [babylonSeen, setBabylonSeen] = useState(tab === "babylon");
  const receipts = useReceipts();
  useEffect(() => { reportAppState("game-dev", { tab, picked }); }, [tab, picked]);

  useEffect(() => { setTab(tabForStage(app, target)); }, [app, target]);
  useEffect(() => { if (tab === "babylon") setBabylonSeen(true); }, [tab]);

  const refresh = useCallback(async () => {
    try {
      setStatus(await callNx("gamedev_status_command", {}));
      setError("");
    } catch (failure) {
      setError(failure?.message || "Game Dev couldn't read the editors.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => { if (!document.hidden) void refresh(); }, 2500);
    return () => clearInterval(timer);
  }, [refresh]);

  const engines = useMemo(() => Object.fromEntries((status?.engines || []).map(row => [row.engine, row])), [status]);
  const sessionsFor = useCallback(engine => sortSessions((status?.sessions || []).filter(row => row.engine === engine)), [status]);

  // The picked session per editor only changes when Paul picks (keepSelection never swaps it).
  useEffect(() => {
    if (!status) return;
    setPicked(current => {
      let changed = false;
      const next = { ...current };
      for (const tabInfo of ENGINE_TABS) {
        if (tabInfo.id === "assets") continue;
        const kept = keepSelection(current[tabInfo.id] || "", sessionsFor(tabInfo.id));
        if (kept !== (current[tabInfo.id] || "")) { next[tabInfo.id] = kept; changed = true; }
      }
      if (changed) local.set("gamedev.picked", next);
      return changed ? next : current;
    });
  }, [status, sessionsFor]);

  const pick = (engine, sessionId) => setPicked(current => {
    const next = { ...current, [engine]: sessionId };
    local.set("gamedev.picked", next);
    return next;
  });

  if (!status && !error) return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (!status) {
    return (
      <div className="nx-pane-honest">
        <Icon as={TriangleAlert} size={22} />
        <strong>Game Dev can't reach the PC</strong>
        <p>{error}</p>
        <Button variant="outline" size="sm" onClick={refresh}>Try again</Button>
      </div>
    );
  }

  const meta = ENGINE_TABS.find(row => row.id === tab) || ENGINE_TABS[0];
  return (
    <div className="nx-gd">
      <div className="nx-gd-tabs">
        <div className="nx-gd-tabrow" role="tablist" aria-label="Editors">
        {ENGINE_TABS.map(row => {
          const state = row.id === "assets" ? null : engineState(engines[row.id]);
          return (
            <button key={row.id} type="button" role="tab" id={`nx-gd-tab-${row.id}`} aria-selected={tab === row.id} aria-controls="nx-gd-panel"
              className={`nx-gd-tab${tab === row.id ? " is-on" : ""}`} onClick={() => setTab(row.id)}>
              {/* The editor's state rides on its own icon, so a dot can never read as the next tab's. */}
              <span className={`nx-gd-tab-icon${state ? ` is-${state.tone}` : ""}`}><Icon as={TAB_ICONS[row.id]} size={14} />{state ? <StatusDot tone={state.tone} /> : null}</span>
              <span>{row.name}</span>
              {state ? <span className="nx-visually-hidden">{state.word}</span> : null}
            </button>
          );
        })}
        </div>
        <IconButton icon={RefreshCw} label="Check editors again" size="sm" onClick={refresh} />
      </div>
      {error ? <p className="nx-gd-banner" role="status"><Icon as={TriangleAlert} size={13} />Showing the last answer: {error}</p> : null}
      <div className="nx-gd-body" id="nx-gd-panel" role="tabpanel" aria-labelledby={`nx-gd-tab-${tab}`}>
        {babylonSeen ? (
          <div className="nx-gd-babylon" hidden={tab !== "babylon"}>
            <BrowserScene status={status} />
            <div className="nx-gd-side nx-scroll">
              <EngineColumn meta={ENGINE_TABS[0]} engine={engines.babylon} sessions={sessionsFor("babylon")} picked={picked.babylon}
                onPick={id => pick("babylon", id)} receipts={receipts} onChanged={refresh} />
            </div>
          </div>
        ) : null}
        {tab === "assets" ? <div className="nx-gd-page nx-scroll"><AssetCheck /></div> : null}
        {tab !== "babylon" && tab !== "assets" ? (
          <div className="nx-gd-page nx-scroll">
            <EngineColumn meta={meta} engine={engines[tab]} sessions={sessionsFor(tab)} picked={picked[tab]}
              onPick={id => pick(tab, id)} receipts={receipts} onChanged={refresh} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------ browser 3D

function BrowserScene({ status }) {
  const [key, setKey] = useState(0);
  // The studio is light in Morning and graphite otherwise. The first look rides in the address;
  // later theme changes are posted to the page, so the scene never reloads for a theme.
  const tone = THEME_SCHEME[useShownTheme()] === "light" ? "light" : "dark";
  const firstTone = useRef(tone).current;
  const frame = useRef(null);
  const path = status.browserUrl || "/api/gamedev/browser";
  const src = `${backendBase()}${path}${path.includes("?") ? "&" : "?"}look=${firstTone}`;
  const standalone = status.browserStandaloneUrl || src;
  const tell = useCallback(() => {
    try { frame.current?.contentWindow?.postMessage({ type: "neyvia:look", tone }, new URL(src, window.location.href).origin); } catch { /* the page asks again on load */ }
  }, [tone, src]);
  useEffect(() => { tell(); }, [tell]);
  return (
    <section className="nx-gd-scene" aria-label="Browser 3D scene">
      <div className="nx-gd-scene-bar">
        <strong>Scene</strong>
        <span className="nx-gd-muted">Drag to look around, click a mesh to select it.</span>
        <span className="nx-head-spacer" />
        <IconButton icon={RefreshCw} label="Reload the scene" size="sm" onClick={() => setKey(value => value + 1)} />
        <a className="nx-gd-link" href={standalone} target="_blank" rel="noreferrer"><Icon as={ExternalLink} size={13} />Open in a tab</a>
      </div>
      <iframe key={key} ref={frame} className="nx-gd-frame" src={src} title="Browser 3D scene editor" onLoad={tell} />
    </section>
  );
}

// ------------------------------------------------------------ one editor

function EngineColumn({ meta, engine, sessions, picked, onPick, receipts, onChanged }) {
  const session = sessions.find(row => row.sessionId === picked) || null;
  return (
    <div className="nx-gd-column">
      <EditorCard meta={meta} engine={engine} sessions={sessions} onChanged={onChanged} />
      <SessionList meta={meta} sessions={sessions} picked={picked} onPick={onPick} />
      {picked && !session ? <p className="nx-gd-note" role="status">The session you picked has ended. Pick another one when the editor is back.</p> : null}
      {session ? <SessionView engineId={meta.id} session={session} receipts={receipts} /> : null}
    </div>
  );
}

function EditorCard({ meta, engine, sessions, onChanged }) {
  const state = engineState(engine);
  const [project, setProject] = useState(() => local.get(`gamedev.project.${meta.id}`, ""));
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [problem, setProblem] = useState("");
  const installed = Boolean(engine?.installed);
  const native = meta.id !== "babylon";

  const setup = async () => {
    setBusy(true); setProblem(""); setResult(null);
    local.set(`gamedev.project.${meta.id}`, project.trim());
    try {
      setResult(await callNx("gamedev_setup_command", { engine: meta.id, projectPath: project.trim() }));
      onChanged();
    } catch (failure) {
      setProblem(friendlyError(failure?.message));
    } finally { setBusy(false); }
  };

  return (
    <section className={`nx-gd-card${state.tone === "gold" ? " is-needs" : ""}`} aria-label={`${meta.name} editor`}>
      <header className="nx-gd-card-head">
        <strong>{meta.name}</strong>
        <span className="nx-gd-state" aria-live="polite"><StatusDot tone={state.tone} />{state.word}</span>
      </header>
      <p className="nx-gd-copy">{meta.blurb} {state.detail}</p>
      {native && engine?.executable ? <p className="nx-gd-meta">Editor <code title={engine.executable}>{shortPath(engine.executable)}</code></p> : null}
      {native && !installed ? (
        <div className="nx-gd-needs">
          <p>Install {meta.editor} on this PC (Neyvia doesn't install editors for you). Then open your project in it here and Neyvia connects by itself.</p>
          <div className="nx-gd-needs-actions">
            {EDITOR_DOWNLOADS[meta.id] ? <a className="nx-btn nx-btn-sm nx-btn-outline" href={EDITOR_DOWNLOADS[meta.id]} target="_blank" rel="noreferrer"><Icon as={ExternalLink} size={13} /><span className="nx-btn-label">Get {meta.name}</span></a> : null}
            <Button size="sm" variant="ghost" icon={RefreshCw} onClick={onChanged}>Check again</Button>
          </div>
        </div>
      ) : null}
      {native && installed ? (
        <form className="nx-gd-setup" onSubmit={event => { event.preventDefault(); if (project.trim()) void setup(); }}>
          <label className="nx-gd-field">
            <span>Project folder</span>
            <input className="nx-input is-mono" value={project} onChange={event => setProject(event.target.value)}
              placeholder="A folder in your game workspace, like my-game" spellCheck={false} />
          </label>
          <Button type="submit" variant={sessions.some(row => row.status === "connected") ? "outline" : "primary"} size="sm" icon={Wrench} disabled={busy || !project.trim()}>
            {busy ? "Setting up" : "Set up"}
          </Button>
        </form>
      ) : null}
      {problem ? <p className="nx-gd-error" role="alert"><Icon as={TriangleAlert} size={13} />{problem}</p> : null}
      {result ? (
        <div className="nx-gd-setup-done" role="status">
          <p><strong>{result.files?.length ? `Added ${result.files.length} file${result.files.length === 1 ? "" : "s"}` : "Already set up"}</strong> in <code title={result.projectPath}>{shortPath(result.projectPath)}</code></p>
          <ol>{(result.instructions || []).map(line => <li key={line}>{line}</li>)}</ol>
        </div>
      ) : null}
    </section>
  );
}

function SessionList({ meta, sessions, picked, onPick }) {
  const [showEnded, setShowEnded] = useState(false);
  const live = sessions.filter(row => row.status !== "disconnected");
  const ended = sessions.filter(row => row.status === "disconnected");
  const rows = showEnded ? sessions : live.length ? live : [];
  useTick(sessions.length > 0, 5000);
  return (
    <section className="nx-gd-card" aria-label="Sessions">
      <header className="nx-gd-card-head">
        <strong>Sessions</strong>
        <span className="nx-gd-muted">{live.length ? `${live.length} open` : "None open"}</span>
      </header>
      {!rows.length ? (
        <p className="nx-gd-copy">
          {meta.id === "babylon" ? "The scene connects when it finishes loading." : `Nothing is connected yet. Open your project in ${meta.editor}.`}
        </p>
      ) : (
        <div className="nx-gd-sessions" role="radiogroup" aria-label={`${meta.name} sessions`}>
          {rows.map(row => {
            const state = sessionState(row);
            return (
              <button key={row.sessionId} type="button" role="radio" aria-checked={picked === row.sessionId}
                className={`nx-gd-session${picked === row.sessionId ? " is-on" : ""}${row.status === "disconnected" ? " is-ended" : ""}`}
                onClick={() => onPick(row.sessionId)}>
                <span className="nx-gd-session-main">
                  <span className="nx-gd-session-title"><StatusDot tone={state.tone} />{sessionLabel(row)}</span>
                  <span className="nx-gd-session-sub">
                    {state.word}{row.lastSeen ? ` · seen ${ago(seenAt(row.lastSeen))}` : ""}{row.studio_id ? ` · Studio ${String(row.studio_id).slice(0, 8)}` : ""}
                  </span>
                </span>
                <span className="nx-gd-session-path" title={row.projectPath}>{folderName(row.projectPath)}</span>
              </button>
            );
          })}
        </div>
      )}
      {ended.length ? (
        <button type="button" className="nx-gd-more" onClick={() => setShowEnded(value => !value)}>
          {showEnded ? "Hide ended sessions" : `Show ${ended.length} ended`}
        </button>
      ) : null}
    </section>
  );
}

/** Official download pages, opened in the browser; Neyvia never downloads an editor itself. */
const EDITOR_DOWNLOADS = {
  godot: "https://godotengine.org/download/windows/", unity: "https://unity.com/download",
  roblox: "https://create.roblox.com/", blender: "https://www.blender.org/download/",
};

// ------------------------------------------------------------ the picked session

function SessionView({ engineId, session, receipts }) {
  const [form, setForm] = useState("");
  const rows = receipts.log[session.sessionId] || [];
  const live = session.status === "connected";
  const caps = session.capabilities || [];
  const tree = latestTree(rows);
  const consoleRows = rows.find(row => row.action === "console" && row.status === "succeeded")?.result?.messages;
  const quick = action => receipts.send(session, action, {});
  const scriptable = engineId === "godot" && session.context === "Edit" && ["inspect", "edit", "validate"].every(cap => caps.includes(cap));

  return (
    <>
      <section className="nx-gd-card" aria-label="Actions">
        <header className="nx-gd-card-head">
          <strong>{sessionLabel(session)}</strong>
          <span className="nx-gd-muted" title={session.projectPath}>{folderName(session.projectPath)}</span>
        </header>
        {!live ? <p className="nx-gd-note">{session.status === "needs_inspection" ? "An action ran out of time. Check the editor, then reconnect it before sending more." : "This session has ended, so its actions are off. Pick a connected session above."}</p> : null}
        <div className="nx-gd-actions">
          {caps.map(action => {
            const needsForm = actionFields(engineId, action).length > 0 && !NO_FORM.has(action);
            const icon = action === "run" ? Play : action === "stop" ? CircleStop : undefined;
            return (
              <Button key={action} size="sm" variant={form === action ? "primary" : "outline"} icon={icon} disabled={!live}
                aria-expanded={needsForm ? form === action : undefined}
                onClick={() => (needsForm ? setForm(current => (current === action ? "" : action)) : quick(action))}>
                {ACTION_WORDS[action] || action}
              </Button>
            );
          })}
        </div>
        {form && live ? <ActionForm key={form} engineId={engineId} action={form} onSend={args => receipts.send(session, form, args)} onClose={() => setForm("")} /> : null}
      </section>
      {scriptable ? <ScriptCard session={session} send={receipts.send} /> : null}
      {caps.includes("export") ? <PipelineCard session={session} send={receipts.send} /> : null}
      {tree ? <Inspection receipt={tree} running={session.context !== "Edit"} /> : null}
      {consoleRows ? <ConsoleView messages={consoleRows} /> : null}
      <ReceiptLog rows={rows} onClear={() => receipts.clear(session.sessionId)} />
    </>
  );
}

function ActionForm({ engineId, action, onSend, onClose }) {
  const fields = actionFields(engineId, action);
  const [values, setValues] = useState(() => initialValues(fields));
  const [text, setText] = useState(() => Object.fromEntries(fields.filter(field => field.kind === "json").map(field => [field.key, pretty(field.initial)])));
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const change = (key, value) => setValues(current => {
    const next = { ...current, [key]: value };
    // A field that only now appears (Godot's Visible after picking that property) starts from its own default.
    for (const field of fields) if (field.when && field.when(next) && !(field.when(current))) next[field.key] = field.initial;
    return next;
  });

  const submit = async event => {
    event.preventDefault();
    setProblem("");
    let args;
    try { args = buildArgs(fields, { ...values, ...text }); } catch (failure) { setProblem(failure.message); return; }
    setBusy(true);
    const receipt = await onSend(args);
    setBusy(false);
    if (receipt?.status === "succeeded") onClose();
  };

  return (
    <form className="nx-gd-form" onSubmit={submit} aria-label={ACTION_WORDS[action] || action}>
      {visibleFields(fields, values).map(field => (
        <Field key={`${field.key}-${field.kind}`} field={field} value={field.kind === "json" ? text[field.key] : values[field.key]}
          onChange={value => (field.kind === "json" ? setText(current => ({ ...current, [field.key]: value })) : change(field.key, value))} />
      ))}
      {problem ? <p className="nx-gd-error" role="alert"><Icon as={TriangleAlert} size={13} />{problem}</p> : null}
      <div className="nx-gd-form-foot">
        <Button type="button" size="sm" onClick={onClose}>Cancel</Button>
        <Button type="submit" size="sm" variant="primary" disabled={busy}>{busy ? "Working" : ACTION_WORDS[action] || action}</Button>
      </div>
    </form>
  );
}

function Field({ field, value, onChange }) {
  if (field.kind === "choice") {
    return (
      <label className="nx-gd-field">
        <span>{field.label}</span>
        <select className="nx-input" value={value} onChange={event => onChange(event.target.value)}>
          {field.options.map(option => <option key={option} value={option}>{option}</option>)}
        </select>
      </label>
    );
  }
  if (field.kind === "bool") {
    return (
      <label className="nx-gd-check">
        <input type="checkbox" checked={Boolean(value)} onChange={event => onChange(event.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  if (field.kind === "vec3") {
    const parts = Array.isArray(value) ? value : [0, 0, 0];
    return (
      <fieldset className="nx-gd-field nx-gd-vec">
        <legend>{field.label}</legend>
        {["x", "y", "z"].map((axis, index) => (
          <label key={axis}>
            <span>{axis}</span>
            <input className="nx-input is-mono" inputMode="decimal" value={parts[index]}
              onChange={event => onChange(parts.map((part, at) => (at === index ? event.target.value : part)))} />
          </label>
        ))}
      </fieldset>
    );
  }
  if (field.kind === "json") {
    return (
      <label className="nx-gd-field">
        <span>{field.label}</span>
        <textarea className="nx-input nx-gd-code" rows={4} value={value} spellCheck={false} onChange={event => onChange(event.target.value)} />
      </label>
    );
  }
  return (
    <label className="nx-gd-field">
      <span>{field.label}</span>
      <input className={`nx-input${field.kind === "text" ? " is-mono" : ""}`} inputMode={field.kind === "number" ? "decimal" : undefined}
        value={value ?? ""} placeholder={field.placeholder} spellCheck={false} onChange={event => onChange(event.target.value)} />
    </label>
  );
}

// ------------------------------------------------------------ Godot scripts

function ScriptCard({ session, send }) {
  const [path, setPath] = useState("res://player.gd");
  const [loaded, setLoaded] = useState(null); // { path, source, sha256 }
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState(null); // { tone, text }
  const dirty = loaded && draft !== loaded.source;

  const run = async (label, work) => {
    setBusy(label); setNote(null);
    try { await work(); } finally { setBusy(""); }
  };
  const open = () => run("open", async () => {
    const receipt = await send(session, "inspect", { path: path.trim() });
    if (receipt.status !== "succeeded") { setNote({ tone: "red", text: friendlyError(receipt.error) }); return; }
    setLoaded(receipt.result); setDraft(receipt.result.source || "");
  });
  const save = () => run("save", async () => {
    const receipt = await send(session, "edit", { path: loaded.path, source: draft, expectedSha256: loaded.sha256 });
    if (receipt.status !== "succeeded") { setNote({ tone: "red", text: friendlyError(receipt.error) }); return; }
    setLoaded({ ...loaded, source: draft, sha256: receipt.result.sha256 });
    setNote({ tone: "idle", text: "Saved in the editor. Check it before you run the game." });
  });
  const check = () => run("check", async () => {
    const receipt = await send(session, "validate", { path: loaded?.path || path.trim() });
    setNote(receipt.status === "succeeded"
      ? { tone: "green", text: "Godot compiled it without errors." }
      : { tone: "red", text: `Godot couldn't compile it${receipt.result?.errorCode != null ? ` (code ${receipt.result.errorCode})` : ""}. Fix it, save, and check again.` });
  });

  return (
    <section className="nx-gd-card" aria-label="Script">
      <header className="nx-gd-card-head"><strong><Icon as={FileCode2} size={14} />Script</strong>
        {loaded ? <code className="nx-gd-muted" title={loaded.sha256}>{loaded.sha256.slice(0, 10)}</code> : null}</header>
      <form className="nx-gd-setup" onSubmit={event => { event.preventDefault(); void open(); }}>
        <label className="nx-gd-field"><span>File</span>
          <input className="nx-input is-mono" value={path} onChange={event => setPath(event.target.value)} spellCheck={false} /></label>
        <Button type="submit" size="sm" variant="outline" disabled={Boolean(busy) || !path.trim().startsWith("res://")}>{busy === "open" ? "Opening" : "Open"}</Button>
      </form>
      {loaded ? (
        <>
          <textarea className="nx-input nx-gd-code nx-gd-source" value={draft} onChange={event => setDraft(event.target.value)}
            spellCheck={false} rows={14} aria-label={`Source of ${loaded.path}`} />
          <div className="nx-gd-form-foot">
            {dirty ? <span className="nx-gd-muted">Not saved</span> : null}
            <Button size="sm" variant={dirty ? "primary" : "outline"} disabled={Boolean(busy) || !dirty} onClick={save}>{busy === "save" ? "Saving" : "Save"}</Button>
            <Button size="sm" variant="outline" disabled={Boolean(busy) || dirty} onClick={check}>{busy === "check" ? "Checking" : "Check script"}</Button>
          </div>
        </>
      ) : null}
      {note ? <p className={`nx-gd-result is-${note.tone}`} role="status"><StatusDot tone={note.tone} />{note.text}</p> : null}
    </section>
  );
}

// ------------------------------------------------------------ export → check → load

function PipelineCard({ session, send }) {
  const caps = session.capabilities || [];
  const [path, setPath] = useState("exports/scene.glb");
  const [steps, setSteps] = useState({}); // step -> { status, text, receipt? }
  const set = (step, value) => setSteps(current => ({ ...current, [step]: value }));
  const busy = Object.values(steps).some(step => step?.status === "running");
  const exported = steps.export?.status === "done" ? steps.export.file : "";
  const checked = steps.check?.status === "done";

  const doRender = async () => {
    set("render", { status: "running", text: "Rendering in the editor" });
    const receipt = await send(session, "render", { path: path.replace(/\.(glb|gltf)$/i, ".png") });
    set("render", receipt.status === "succeeded" ? { status: "done", text: "Rendered" } : { status: "failed", text: friendlyError(receipt.error) });
  };
  const doExport = async () => {
    set("export", { status: "running", text: "Exporting" }); set("check", null); set("load", null);
    const receipt = await send(session, "export", { path: path.trim() });
    if (receipt.status !== "succeeded") { set("export", { status: "failed", text: friendlyError(receipt.error) }); return; }
    const bytes = receipt.result?.bytes;
    set("export", { status: "done", file: receipt.result?.path || path.trim(), text: `Saved${bytes ? ` · ${(bytes / 1024).toFixed(1)} KB` : ""}` });
  };
  const doCheck = async () => {
    set("check", { status: "running", text: "Checking with the glTF validator" });
    try {
      const report = await callNx("gamedev_asset_validate_command", { path: exported });
      set("check", report.valid
        ? { status: "done", text: `Valid · ${report.warnings?.length || 0} warnings`, report }
        : { status: "failed", text: `${report.errors?.length || 0} errors: ${report.errors?.[0]?.message || "see the validator report"}`, report });
    } catch (failure) { set("check", { status: "failed", text: friendlyError(failure?.message) }); }
  };
  const doLoad = async () => {
    set("load", { status: "running", text: "Loading in the engine" });
    const receipt = await send(session, "load_asset", { path: path.trim() });
    set("load", receipt.status === "succeeded"
      ? { status: "done", text: `Loaded ${(receipt.result?.loaded || [receipt.result?.node]).filter(Boolean).length || ""} ${receipt.result?.loaded ? "meshes" : "node"}`.replace("  ", " ") }
      : { status: "failed", text: friendlyError(receipt.error) });
  };

  const rows = [
    ...(caps.includes("render") ? [{ id: "render", title: "Render", run: doRender, ready: true }] : []),
    { id: "export", title: "Export", run: doExport, ready: true },
    { id: "check", title: "Check the file", run: doCheck, ready: Boolean(exported) },
    { id: "load", title: "Load in the engine", run: doLoad, ready: checked && caps.includes("load_asset") },
  ];
  const tone = step => (step?.status === "done" ? "green" : step?.status === "failed" ? "red" : step?.status === "running" ? "live" : "idle");

  return (
    <section className="nx-gd-card" aria-label="Export, check and load">
      <header className="nx-gd-card-head"><strong>Export, check, load</strong></header>
      <label className="nx-gd-field"><span>File</span>
        <input className="nx-input is-mono" value={path} onChange={event => setPath(event.target.value)} spellCheck={false} /></label>
      <ol className="nx-gd-steps">
        {rows.map((row, index) => {
          const step = steps[row.id];
          return (
            <li key={row.id} className="nx-gd-step">
              <span className="nx-gd-step-n">{index + 1}</span>
              <span className="nx-gd-step-main">
                <strong>{row.title}</strong>
                <span className="nx-gd-step-text"><StatusDot tone={tone(step)} pulse={step?.status === "running"} />{step?.text || (row.ready ? "Ready" : "After the step before")}</span>
              </span>
              <Button size="sm" variant="outline" disabled={busy || !row.ready} onClick={row.run}>{row.title.split(" ")[0]}</Button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

// ------------------------------------------------------------ inspection, console, log

function TreeNode({ node, depth = 0 }) {
  const children = node.children || [];
  const label = (
    <>
      <span className="nx-gd-node-name">{node.name}</span>
      <span className="nx-gd-node-type">{node.type}</span>
      {node.position ? <code className="nx-gd-node-pos">{formatVector(node.position)}</code> : null}
    </>
  );
  const state = node.state ? <code className="nx-gd-node-state">{pretty(node.state).replace(/\s+/g, " ")}</code> : null;
  if (!children.length) return <li className="nx-gd-node"><span className="nx-gd-node-row">{label}</span>{state}</li>;
  return (
    <li className="nx-gd-node">
      <details open={depth < 2}>
        <summary className="nx-gd-node-row">{label}</summary>
        {state}
        <ul>{children.map(child => <TreeNode key={child.path || child.name} node={child} depth={depth + 1} />)}</ul>
      </details>
    </li>
  );
}

function Inspection({ receipt, running }) {
  const result = receipt.result || {};
  return (
    <section className="nx-gd-card" aria-label="Inspection">
      <header className="nx-gd-card-head"><strong><Icon as={ListTree} size={14} />{running ? "What the game sees" : "What the editor sees"}</strong>
        <span className="nx-gd-muted">{ago(receipt.finishedAt || receipt.createdAt)}{result.frames != null ? ` · frame ${result.frames}` : ""}{result.playing != null ? (result.playing ? " · game running" : " · game stopped") : ""}</span></header>
      {result.scene ? <p className="nx-gd-meta">Scene <code>{result.scene}</code></p> : null}
      {result.interaction ? <p className="nx-gd-meta">Game answered <code>{pretty(result.interaction).replace(/\s+/g, " ")}</code></p> : null}
      <ul className="nx-gd-tree">{result.tree ? <TreeNode node={result.tree} /> : null}</ul>
    </section>
  );
}

function ConsoleView({ messages }) {
  return (
    <section className="nx-gd-card" aria-label="Console">
      <header className="nx-gd-card-head"><strong><Icon as={ScrollText} size={14} />Console</strong><span className="nx-gd-muted">{messages.length} lines</span></header>
      {messages.length ? (
        <pre className="nx-gd-pre">{messages.map(row => `${row.level ? `${row.level}: ` : ""}${row.message ?? pretty(row)}`).join("\n")}</pre>
      ) : <p className="nx-gd-copy">Nothing logged yet.</p>}
    </section>
  );
}

function ReceiptLog({ rows, onClear }) {
  useTick(rows.some(row => !isDone(row.status)), 1000);
  return (
    <section className="nx-gd-card" aria-label="Action log">
      <header className="nx-gd-card-head">
        <strong>Action log</strong>
        <span className="nx-gd-muted">{rows.length ? `${rows.length} from this screen` : ""}</span>
        <span className="nx-head-spacer" />
        {rows.length ? <Button size="sm" onClick={onClear}>Clear</Button> : null}
      </header>
      {!rows.length ? <p className="nx-gd-copy">Actions you send show here with the editor's answer.</p> : (
        <ul className="nx-gd-log" aria-live="polite">
          {rows.map(row => {
            const state = receiptState(row);
            return (
              <li key={row.requestId}>
                <details>
                  <summary className="nx-gd-log-row">
                    <StatusDot tone={state.tone} pulse={state.pulse} />
                    <span className="nx-gd-log-action">{ACTION_WORDS[row.action] || row.action}</span>
                    <span className="nx-gd-log-state">{state.word}</span>
                    {row.error ? <span className="nx-gd-log-error">{friendlyError(row.error)}</span> : <span className="nx-gd-log-error" />}
                    <span className="nx-gd-log-time">{row.elapsedMs != null && isDone(row.status) ? `${(row.elapsedMs / 1000).toFixed(1)}s · ` : ""}{ago(row.createdAt)}</span>
                  </summary>
                  <div className="nx-gd-log-body">
                    {Object.keys(row.args || {}).length ? <><span className="nx-tag">Sent</span><pre className="nx-gd-pre">{pretty(row.args).slice(0, 4000)}</pre></> : null}
                    {row.result && Object.keys(row.result).length ? <><span className="nx-tag">Answer</span><pre className="nx-gd-pre">{pretty(row.result).slice(0, 8000)}</pre></> : null}
                    {row.error ? <><span className="nx-tag">Editor said</span><pre className="nx-gd-pre">{row.error}</pre></> : null}
                    <p className="nx-gd-meta">Receipt <code>{row.requestId}</code>
                      <IconButton icon={Copy} size="sm" label="Copy receipt id" onClick={() => copy(row.requestId)} /></p>
                  </div>
                </details>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ------------------------------------------------------------ asset check tab

function AssetCheck() {
  const [path, setPath] = useState(() => local.get("gamedev.asset", ""));
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const [problem, setProblem] = useState("");

  const check = async () => {
    setBusy(true); setProblem(""); setReport(null);
    local.set("gamedev.asset", path.trim());
    try { setReport(await callNx("gamedev_asset_validate_command", { path: path.trim() })); } catch (failure) { setProblem(friendlyError(failure?.message)); } finally { setBusy(false); }
  };

  const info = report?.summary || {};
  return (
    <div className="nx-gd-column">
      <section className="nx-gd-card" aria-label="Asset check">
        <header className="nx-gd-card-head"><strong>Check a 3D file</strong></header>
        <p className="nx-gd-copy">Runs the official Khronos glTF validator on a .glb or .gltf in the game workspace, with the files it points to. An engine only loads a file that passes.</p>
        <form className="nx-gd-setup" onSubmit={event => { event.preventDefault(); if (path.trim()) void check(); }}>
          <label className="nx-gd-field"><span>File</span>
            <input className="nx-input is-mono" value={path} onChange={event => setPath(event.target.value)} placeholder="exports/scene.glb" spellCheck={false} /></label>
          <Button type="submit" variant="primary" icon={FileCheck2} disabled={busy || !path.trim()}>{busy ? "Checking" : "Check"}</Button>
        </form>
        {problem ? <p className="nx-gd-error" role="alert"><Icon as={TriangleAlert} size={13} />{problem}</p> : null}
      </section>
      {report ? (
        <section className="nx-gd-card" aria-label="Validator report">
          <header className="nx-gd-card-head">
            <strong>{report.valid ? "Valid" : "Not valid"}</strong>
            <span className="nx-gd-state"><StatusDot tone={report.valid ? "green" : "red"} />{report.errors?.length || 0} errors · {report.warnings?.length || 0} warnings</span>
          </header>
          <dl className="nx-gd-facts">
            <dt>File</dt><dd><code title={report.path}>{shortPath(report.path)}</code></dd>
            <dt>Format</dt><dd>{String(report.format || "").toUpperCase()} · {(report.bytes / 1024).toFixed(1)} KB</dd>
            {info.generator ? <><dt>Made by</dt><dd>{info.generator}</dd></> : null}
            {info.meshCount != null ? <><dt>Meshes</dt><dd>{info.meshCount}</dd></> : null}
            {info.totalVertexCount != null ? <><dt>Vertices</dt><dd>{info.totalVertexCount}</dd></> : null}
            <dt>Checked by</dt><dd>{report.validator} {report.validatorVersion}</dd>
            <dt>SHA-256</dt><dd><code title={report.sha256}>{String(report.sha256 || "").slice(0, 16)}</code>
              <IconButton icon={Copy} size="sm" label="Copy SHA-256" onClick={() => copy(report.sha256)} /></dd>
          </dl>
          {[...(report.errors || []), ...(report.warnings || [])].length ? (
            <ul className="nx-gd-issues">
              {[...(report.errors || []).map(row => ({ ...row, bad: true })), ...(report.warnings || [])].slice(0, 30).map((row, index) => (
                <li key={`${row.code}-${index}`} className={row.bad ? "is-bad" : ""}><code>{row.code}</code> {row.message}{row.pointer ? <span className="nx-gd-muted"> at {row.pointer}</span> : null}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
