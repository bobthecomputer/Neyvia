import { useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, ArrowLeft, Box, BrainCircuit, Bug, ChartColumn, Clapperboard, Code2, FileSpreadsheet, FileText,
  FlaskConical, FolderOpen, Gamepad2, Hammer, ImageIcon, Layers, ListChecks, Mountain, Palette, PenLine, Play, Puzzle,
  NotebookPen, Search, ShieldCheck, Sigma, Smartphone, TrendingUp, Wrench,
} from "lucide-react";

import "./nxLauncher.css";
import { Icon, Kbd, useFocusTrap } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { useApps } from "./nxApps.js";
import { searchLauncher } from "./nxLauncherModel.js";
import { openFromUi } from "./nxOutputsApi.js";

// A ready app opens through the backend's app.open (the model's own path); a coming one shows its honest page locally.
const openTile = (app, suite, ready) => (ready ? void openFromUi(app, { suite }) : os.openApp(app, suite));

// Ctrl+Space: the four app suites, each opening to its apps, and one search
// across apps, actions, projects and chats (07 §R1, §R7.4).

const SUITE_ICONS = { documents: FileText, "game-dev": Gamepad2, studio: Palette, lab: FlaskConical };
const APP_ICONS = {
  pdf: FileText, notes: NotebookPen, files: FolderOpen, "doc-editor": PenLine, latex: Sigma, spreadsheets: FileSpreadsheet,
  unity: Box, roblox: Layers, godot: Gamepad2, "asset-checks": Mountain, playtest: Play,
  "image-studio": ImageIcon, "mobile-studio": Smartphone, video: Clapperboard, visualization: ChartColumn, quiz: ListChecks,
  decompile: Code2, "hill-climb": TrendingUp, modding: Puzzle, security: ShieldCheck,
};
const GROUP_ICONS = { Actions: Wrench, Apps: AppWindow, Projects: Hammer, Chats: BrainCircuit };

function moveFocus(container, step) {
  const items = [...(container?.querySelectorAll("[data-launch-item]:not(:disabled)") || [])];
  if (!items.length) return;
  const index = items.indexOf(document.activeElement);
  items[(index + step + items.length) % items.length].focus();
}

function Tile({ icon, title, subtitle, coming, onClick, big = false }) {
  return (
    <button type="button" data-launch-item className={`nx-tile${big ? " is-big" : ""}${coming ? " is-coming" : ""}`}
      onClick={onClick} disabled={coming} aria-description={coming ? "Coming soon" : undefined}>
      <span className="nx-tile-icon"><Icon as={icon} size={big ? 22 : 18} /></span>
      <span className="nx-tile-text">
        <span className="nx-tile-title">{title}{coming ? <span className="nx-tile-tag">Coming</span> : null}</span>
        {subtitle ? <span className="nx-tile-sub">{subtitle}</span> : null}
      </span>
    </button>
  );
}

/** `demo` ({ query, suite, cursor }) shows a scripted, look-only launcher (the tour): always open, no keys or focus. */
export function NxLauncher({ actions, projects, chats, onRun, demo = null }) {
  const shown = useOs(state => state.launcher);
  const askedQuery = useOs(state => state.launcherQuery);
  const open = demo ? true : shown;
  const { suites, source } = useApps();
  const [ownQuery, setQuery] = useState("");
  const [ownSuite, setSuiteId] = useState(null);
  const [ownCursor, setCursor] = useState(0);
  const query = demo ? demo.query || "" : ownQuery;
  const suiteId = demo ? demo.suite || null : ownSuite;
  const cursor = demo ? demo.cursor || 0 : ownCursor;
  const input = useRef(null);
  const body = useRef(null);
  const dialog = useRef(null);
  useFocusTrap(dialog, open && !demo);
  const suite = suites.find(entry => entry.id === suiteId) || null;

  useEffect(() => {
    if (demo) return undefined;
    const onKey = event => {
      if (event.ctrlKey && (event.code === "Space" || event.key === " ")) {
        event.preventDefault();
        os.setLauncher(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, demo]);

  useEffect(() => {
    if (demo) return undefined;
    if (!open) { setQuery(""); setSuiteId(null); return; }
    if (askedQuery) setQuery(askedQuery);
    const previous = document.activeElement;
    requestAnimationFrame(() => input.current?.focus());
    return () => previous?.focus?.();
  }, [open, demo, askedQuery]);

  const results = useMemo(() => searchLauncher(query, { suites, actions, projects, chats }), [query, suites, actions, projects, chats]);
  useEffect(() => setCursor(0), [query]);

  if (!open) return null;
  const close = () => { if (!demo) os.setLauncher(false); };
  const run = result => {
    if (!result || result.disabled || demo) return;
    const payload = result.payload;
    if (payload.type === "suite") { setSuiteId(payload.suite); setQuery(""); input.current?.focus(); return; }
    if (payload.type === "app") { openTile(payload.app, payload.suite, true); return; }
    close();
    onRun(payload);
  };

  const onKeyDown = event => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (query) setQuery("");
      else if (suite) setSuiteId(null);
      else close();
      return;
    }
    if (event.key === "Backspace" && !query && suite && event.target === input.current) { setSuiteId(null); return; }
    if (query) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setCursor(current => (current + step + results.length) % Math.max(1, results.length));
      } else if (event.key === "Enter") {
        event.preventDefault();
        run(results[cursor]);
      }
      return;
    }
    if (["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(event.key) && event.target !== input.current || event.key === "ArrowDown" && event.target === input.current) {
      event.preventDefault();
      moveFocus(body.current, event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 1);
    }
  };

  let lastGroup = "";
  return (
    <div className="nx-launcher-scrim" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-label="Apps and search" className="nx-launcher" onKeyDown={onKeyDown}>
        <header className="nx-launcher-head">
          {suite && !query ? (
            <button type="button" className="nx-launcher-back" aria-label="All suites" onClick={() => setSuiteId(null)}>
              <Icon as={ArrowLeft} size={16} />
            </button>
          ) : <Icon as={Search} size={16} className="nx-launcher-glass" />}
          <input ref={input} value={query} onChange={event => setQuery(event.target.value)}
            placeholder={suite ? `Search ${suite.name}, or anything` : "Search apps, projects, chats and actions"}
            aria-label="Search" role="combobox" aria-expanded={Boolean(query)} aria-controls="nx-launch-results"
            aria-activedescendant={query && results[cursor] ? `nx-launch-${cursor}` : undefined} />
          <Kbd>Esc</Kbd>
        </header>

        <div className="nx-launcher-body nx-scroll" ref={body}>
          {query ? (
            results.length ? (
              <div role="listbox" id="nx-launch-results" aria-label="Results" className="nx-results">
                {results.map((result, index) => {
                  const head = result.group !== lastGroup ? (lastGroup = result.group) : null;
                  return (
                    <div key={result.key}>
                      {head ? <div className="nx-results-group"><Icon as={GROUP_ICONS[head]} size={12} />{head}</div> : null}
                      <div role="option" id={`nx-launch-${index}`} aria-selected={index === cursor} aria-disabled={result.disabled || undefined}
                        className={`nx-result${index === cursor ? " is-on" : ""}${result.disabled ? " is-disabled" : ""}`}
                        onMouseMove={() => setCursor(index)} onClick={() => run(result)}>
                        <span className="nx-result-title">{result.title}</span>
                        {result.subtitle ? <span className="nx-result-sub">{result.subtitle}</span> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : <p className="nx-launcher-empty">Nothing matches “{query}”.</p>
          ) : suite ? (
            <div className="nx-launcher-suite" key={suite.id}>
              <h2><Icon as={SUITE_ICONS[suite.id] || AppWindow} size={16} />{suite.name}</h2>
              <div className="nx-tiles">
                {suite.apps.map(app => (
                  <Tile key={app.id} icon={APP_ICONS[app.id] || Bug} title={app.name} subtitle={app.description}
                    coming={app.status !== "ready"} onClick={() => openTile(app.id, suite.id, app.status === "ready")} />
                ))}
              </div>
            </div>
          ) : (
            <div className="nx-launcher-home">
              <div className="nx-tiles is-suites">
                {suites.map(entry => {
                  const ready = entry.apps.filter(app => app.status === "ready").length;
                  return (
                    <Tile key={entry.id} big icon={SUITE_ICONS[entry.id] || AppWindow} title={entry.name}
                      subtitle={`${entry.description}${entry.description ? " · " : ""}${ready ? `${ready} ready` : "Coming"}`}
                      onClick={() => { setSuiteId(entry.id); input.current?.focus(); }} />
                  );
                })}
              </div>
              <p className="nx-launcher-note">
                Chat, the workspace, runtime and missions are Neyvia itself: always here, no app to open.
                {source === "plan" ? " The app list is the plan's, all Coming, because the app registry didn't answer." : null}
                {source === "mock" ? " App list from the mock backend." : null}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
