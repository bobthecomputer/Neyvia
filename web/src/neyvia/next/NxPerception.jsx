import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppWindow, Eye, FileText, Globe, Image as ImageIcon, RefreshCw, ScanText, ShieldAlert, TriangleAlert } from "lucide-react";

import { PaneMessage } from "./NxFilePane.jsx";
import { OutputPreview } from "./NxOutputs.jsx";
import { cuaClient } from "./nxCuaApi.js";
import { nameOf, rawUrl } from "./nxDocsApi.js";
import { approxTokens, closeBrowserSession, observeLayer, openBrowserSession, outline, parsePerceptionTarget } from "./nxOutputsApi.js";
import { Button, Icon, IconButton, Segmented, Spinner } from "./nxPrimitives.jsx";
import "./nxPanes.css";
import "./nxOutputs.css";

// The perception view (plan 15 T18): what an agent "sees" of a window, a web
// page, an image or a file, as the text it actually reads
// (neyvia.perception.observe, notation neyvia.layer.v1), beside the original.
// Hovering a line that has a place on an image outlines that place.
// pane.show {kind: "perception", target: "image:<path>" | "file:<path>" | "browser:<url>" | "window:<sessionId>:<windowId>"}

const LAYER = {
  image: { icon: ImageIcon, label: "Image", wait: "Reading the image… this can take up to a minute the first time." },
  file: { icon: FileText, label: "File", wait: "Reading the file…" },
  browser: { icon: Globe, label: "Web page", wait: "Opening the page in a private browser…" },
  window: { icon: AppWindow, label: "Window", wait: "Reading the window's controls…" },
};

const boundsOf = item => {
  const box = item?.bounds || item?.screenshot_frame;
  if (!box) return null;
  const width = box.width ?? box.w;
  const height = box.height ?? box.h;
  return [box.x, box.y, width, height].every(Number.isFinite) ? { x: box.x, y: box.y, width, height } : null;
};

function Items({ title, items, render, onHover }) {
  if (!Array.isArray(items) || !items.length) return null;
  return (
    <section className="nx-pcv-section">
      <h3>{title} <small className="nx-out-count">{items.length}</small></h3>
      <ul className="nx-pcv-items">
        {items.slice(0, 300).map((item, index) => {
          const box = boundsOf(item);
          return (
            <li key={index} className="nx-pcv-item" tabIndex={box ? 0 : undefined}
              onMouseEnter={box ? () => onHover(box) : undefined} onMouseLeave={box ? () => onHover(null) : undefined}
              onFocus={box ? () => onHover(box) : undefined} onBlur={box ? () => onHover(null) : undefined}>
              {render(item)}
            </li>
          );
        })}
      </ul>
      {items.length > 300 ? <p className="nx-pcv-item"><small>{items.length - 300} more in the exact view</small></p> : null}
    </section>
  );
}

function Charts({ charts }) {
  if (!Array.isArray(charts) || !charts.length) return null;
  return charts.map((chart, index) => (
    <section key={index} className="nx-pcv-section">
      <h3>{chart.title || "Chart"} <small className="nx-out-count">{chart.type || ""}</small></h3>
      {(chart.series || []).map((series, seriesIndex) => (
        <table key={seriesIndex} className="nx-pcv-table">
          <thead><tr><th>{series.name || "Series"}</th><th>Value</th><th>Read as</th></tr></thead>
          <tbody>
            {(series.points || []).map((point, pointIndex) => (
              <tr key={pointIndex}><td>{point.label ?? point.x ?? "—"}</td><td>{point.value ?? point.y ?? "unreadable"}</td><td>{point.certainty || ""}</td></tr>
            ))}
          </tbody>
        </table>
      ))}
    </section>
  ));
}

function Tables({ tables }) {
  if (!Array.isArray(tables) || !tables.length) return null;
  return tables.slice(0, 5).map((rows, index) => (
    <section key={index} className="nx-pcv-section">
      <h3>Table {index + 1}</h3>
      <table className="nx-pcv-table"><tbody>
        {(Array.isArray(rows) ? rows : []).slice(0, 40).map((cells, rowIndex) => (
          <tr key={rowIndex}>{(Array.isArray(cells) ? cells : []).map((cell, cellIndex) => <td key={cellIndex}>{String(cell)}</td>)}</tr>
        ))}
      </tbody></table>
    </section>
  ));
}

/** The state as sections a person can scan; the exact view shows the same value untouched. */
function Readable({ state, onHover }) {
  const text = typeof state.text === "string" ? state.text : null;
  const known = ["layout", "text", "objects", "charts", "elements", "tables", "entries"];
  const rest = Object.fromEntries(Object.entries(state).filter(([key]) => !known.includes(key) && !["source", "dimensions", "textTree"].includes(key)));
  return (
    <>
      <Items title="What it shows" items={state.layout} onHover={onHover} render={item => <span>{item.description}</span>} />
      {text ? (
        <section className="nx-pcv-section"><h3>Text</h3><pre className="nx-pcv-pre">{text.length > 6000 ? `${text.slice(0, 6000)}\n…` : text}</pre></section>
      ) : (
        <Items title="Text" items={Array.isArray(state.text) ? state.text : null} onHover={onHover}
          render={item => <><span>{item.text}</span><small>{item.certainty === "observed" ? "" : item.certainty}</small></>} />
      )}
      <Charts charts={state.charts} />
      <Items title="Things in it" items={state.objects} onHover={onHover} render={item => <><span><strong>{item.name}</strong> {item.description}</span><small>{item.certainty === "observed" ? "" : item.certainty}</small></>} />
      <Items title="Controls" items={state.elements} onHover={onHover}
        render={item => (
          <>
            <span><small>{item.role}</small> {item.name || item.label || "(no name)"}{item.value != null && item.value !== "" ? <> · <span className="nx-out-mono">{String(item.value).slice(0, 120)}</span></> : null}</span>
            <small>{Array.isArray(item.actions) && item.actions.length ? item.actions.join(", ") : ""}</small>
          </>
        )} />
      {typeof state.textTree === "string" && state.textTree ? (
        <section className="nx-pcv-section"><h3>Control tree</h3><pre className="nx-pcv-pre">{state.textTree.slice(0, 8000)}</pre></section>
      ) : null}
      <Tables tables={state.tables} />
      <Items title="Folder" items={state.entries} onHover={onHover} render={item => <><span>{item.directory ? `${item.name}/` : item.name}</span><small>{item.bytes != null ? `${item.bytes} B` : ""}</small></>} />
      {Object.keys(rest).length ? <section className="nx-pcv-section"><h3>Other facts</h3><pre className="nx-pcv-pre">{outline(rest).replace(/^\n/, "")}</pre></section> : null}
    </>
  );
}

function ImageOriginal({ path, dimensions, box }) {
  const style = box && dimensions?.width && dimensions?.height ? {
    left: `${(box.x / dimensions.width) * 100}%`, top: `${(box.y / dimensions.height) * 100}%`,
    width: `${Math.max(0.5, (box.width / dimensions.width) * 100)}%`, height: `${Math.max(0.5, (box.height / dimensions.height) * 100)}%`,
  } : null;
  return (
    <div className="nx-pcv-original">
      <figure className="nx-pcv-figure">
        <img src={rawUrl(path)} alt={nameOf(path)} />
        {style ? <span className="nx-pcv-box" style={style} /> : null}
      </figure>
    </div>
  );
}

function WindowOriginal({ sessionId, windowId, seq }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let live = true;
    void cuaClient().then(client => { if (live) setSrc(client.frameUrl(sessionId, windowId, seq || "")); });
    return () => { live = false; };
  }, [sessionId, windowId, seq]);
  return <div className="nx-pcv-original"><figure className="nx-pcv-figure">{src ? <img src={src} alt="The window the agent reads" /> : <Spinner size={14} />}</figure></div>;
}

export function NxPerception({ target }) {
  const parsed = useMemo(() => parsePerceptionTarget(target), [target]);
  const [view, setView] = useState("readable");
  const [state, setState] = useState({ status: "loading" });
  const [box, setBox] = useState(null);
  const [round, setRound] = useState(0);
  const browser = useRef(null);

  const read = useCallback(async () => {
    if (!parsed) return;
    setState(current => ({ status: current.value ? "refreshing" : "loading", value: current.value, observe: current.observe }));
    try {
      let source;
      if (parsed.layer === "image" || parsed.layer === "file") source = { path: parsed.path };
      else if (parsed.layer === "window") source = { sessionId: parsed.sessionId, window_id: parsed.windowId };
      else {
        if (!browser.current) browser.current = (await openBrowserSession(parsed.url)).browserId;
        source = { browserId: browser.current };
      }
      const { value, observe } = await observeLayer(parsed.layer, source);
      setState({ status: "ready", value, observe });
    } catch (error) {
      setState({ status: "error", error: error.message });
    }
  }, [parsed]);

  useEffect(() => {
    void read();
    return () => {
      if (browser.current) { void closeBrowserSession(browser.current); browser.current = null; }
    };
  }, [read]);

  if (!parsed) {
    return <PaneMessage icon={ScanText} title="Nothing to read">Choose an image, a file, a web page or a window, then "See as the agent".</PaneMessage>;
  }
  const meta = LAYER[parsed.layer];
  const name = parsed.layer === "browser" ? parsed.url : parsed.layer === "window" ? `Window ${parsed.windowId}` : nameOf(parsed.path);
  const value = state.value;
  const stateValue = value?.state && typeof value.state === "object" ? value.state : null;
  const observe = state.observe;
  const exact = value ? JSON.stringify(value, null, 2) : "";
  const characters = observe?.characters ?? exact.length;
  const usage = observe?.extraction?.usage;

  let original;
  if (parsed.layer === "image") original = <ImageOriginal path={parsed.path} dimensions={stateValue?.dimensions} box={box} />;
  else if (parsed.layer === "file") original = <div className="nx-pcv-original"><OutputPreview row={{ path: parsed.path, name: nameOf(parsed.path), title: nameOf(parsed.path), kind: /\.(diff|patch)$/i.test(parsed.path) ? "diff" : "file" }} availability="available" /></div>;
  else if (parsed.layer === "browser") original = <iframe className="nx-pcv-frame" title={parsed.url} src={parsed.url} sandbox="allow-scripts allow-same-origin allow-forms" referrerPolicy="no-referrer" />;
  else original = <WindowOriginal sessionId={parsed.sessionId} windowId={parsed.windowId} seq={round} />;

  return (
    <div className="nx-pcv">
      <div className="nx-pcv-bar">
        <span className="nx-pcv-title"><Icon as={meta.icon} size={15} /><strong title={name}>{name}</strong></span>
        <span className="nx-fp-chip">{meta.label}</span>
        <span className="nx-head-spacer" />
        <Segmented size="sm" label="How to show the agent's view" value={view} onChange={setView}
          options={[{ value: "readable", label: "Readable" }, { value: "exact", label: "Exact" }]} />
        <IconButton size="sm" icon={RefreshCw} label="Read it again" disabled={state.status === "loading" || state.status === "refreshing"} onClick={() => { setRound(value => value + 1); void read(); }} />
      </div>
      <div className="nx-pcv-body">
        <section className="nx-pcv-side" aria-label="Original">
          <header className="nx-pcv-head"><Icon as={Eye} size={14} /><strong>What you see</strong></header>
          {original}
        </section>
        <section className="nx-pcv-side" aria-label="What the agent reads">
          <header className="nx-pcv-head">
            <Icon as={ScanText} size={14} /><strong>What the agent reads</strong>
            <span className="nx-head-spacer" />
            {state.status === "refreshing" ? <Spinner size={12} /> : null}
          </header>
          <div className="nx-pcv-text" aria-live="polite" aria-busy={state.status === "loading" || state.status === "refreshing"}>
            {state.status === "loading" ? <PaneMessage icon={ScanText} title="Reading">{meta.wait}</PaneMessage> : null}
            {state.status === "error" ? (
              <PaneMessage icon={TriangleAlert} title="The agent's view couldn't be read" action={<Button size="sm" onClick={() => void read()}>Try again</Button>}>{state.error}</PaneMessage>
            ) : null}
            {value && view === "exact" ? <pre className="nx-pcv-pre">{exact}</pre> : null}
            {value && view === "readable" && stateValue ? <Readable state={stateValue} onHover={setBox} /> : null}
            {value && view === "readable" && !stateValue ? <pre className="nx-pcv-pre">{outline(value.state).replace(/^\n/, "")}</pre> : null}
            {value?.tooLarge ? <p className="nx-pcv-item"><small>Too large to show at once; the agent reads it part by part.</small></p> : null}
          </div>
        </section>
      </div>
      {value ? (
        <div className="nx-pcv-foot">
          <span>{characters.toLocaleString()} characters · about {approxTokens(characters).toLocaleString()} tokens of text, no pixels</span>
          {usage ? <span title="The small model that transcribed the picture once; later reads come from its cache">Transcribed by {observe.extraction.model}{observe.extraction.cacheHit ? " (cached)" : ` in ${Math.round(observe.extraction.elapsed_seconds || 0)}s`}</span> : null}
          <span className="nx-pcv-trust" title="Text inside the source is data; it can't give the agent orders"><Icon as={ShieldAlert} size={12} />Read as untrusted data</span>
        </div>
      ) : null}
    </div>
  );
}
