import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BatteryFull, Check, ChevronLeft, ChevronRight, CircleAlert, CircleDashed, Download, Lock, Minus, RotateCw, Signal, Square, Wifi, X } from "lucide-react";

// App Factory's canvas: the app being made, shown live in a frame that fits its target (a window
// for a native desktop app, a browser for a Neyvia local app, a phone for iPhone or Android), with
// the build flowing along under it. Before the real build exists, the frame shows a sketch drawn
// from the brief with the same layout, words and colours the generated app will have
// (grant_agent/app_factory.py _theme_tokens and _starter_copy); the real app replaces it the
// moment its preview passes the checks. Nothing here invents a result: the sketch says it is one.

export const FRAMES = [
  { id: "window", label: "Window" },
  { id: "browser", label: "Browser" },
  { id: "iphone", label: "iPhone" },
  { id: "android", label: "Android" },
];
export const frameForTarget = target => (target === "desktop" ? "window" : target === "ios-studio" ? "iphone" : target === "android" ? "android" : "browser");

// The size the app is drawn at inside each frame (CSS pixels), before it is scaled to fit.
const VIRTUAL = { window: { width: 1040, height: 680 }, browser: { width: 1100, height: 700 }, iphone: { width: 393, height: 852 }, android: { width: 412, height: 915 } };
const CHROME = { window: 34, browser: 42 };

// The generated app's colours (app_factory.py _theme_tokens).
const TONES = {
  midnight: { page: "#0e1115", panel: "#161b21", panelStrong: "#f3f6f8", ink: "#f5f7f8", muted: "#98a4ad", line: "#29323a", accent: "#72e2b5", accentInk: "#082218" },
  paper: { page: "#f1eee6", panel: "#fffdf8", panelStrong: "#1e2625", ink: "#1d2524", muted: "#66706d", line: "#d8d2c7", accent: "#2f7c67", accentInk: "#f7fffb" },
  warm: { page: "#17120f", panel: "#231b17", panelStrong: "#f3e7da", ink: "#f6eee6", muted: "#b8a79a", line: "#3b2e27", accent: "#e48d5d", accentInk: "#26150d" },
};
// The generated app's words (app_factory.py _starter_copy and _template_for).
const COPY = {
  notes: { noun: "note", nouns: "notes", verb: "Save note", placeholder: "Write one useful thought…", emptyTitle: "No notes yet", emptyDetail: "Your first saved note will appear here and remain on this device." },
  checklist: { noun: "item", nouns: "items", verb: "Add item", placeholder: "Add the next useful step…", emptyTitle: "Nothing queued", emptyDetail: "Add the first item. It will stay saved locally on this device." },
};
export const templateFor = (brief, requested) => (requested && requested !== "auto" && requested !== "capability" ? requested
  : /\b(note|notes|journal|diary|memo|writing|ideas?)\b/i.test(String(brief || "")) ? "notes" : "checklist");

export const SAMPLE = {
  name: "Pocket Field Notes",
  brief: "Capture field observations, find them quickly, and export a portable record.",
  template: "notes", theme: "midnight",
  items: ["Heron on the north pond at 07:40, two juveniles.", "Soil is dry near plot 4; check the drip line.", "Trail marker 12 needs fresh paint."],
};

const channels = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
const alpha = (hex, a) => `rgba(${channels(hex).join(", ")}, ${a})`;
const mixHex = (from, to, amount) => `rgb(${channels(from).map((v, i) => Math.round(v + (channels(to)[i] - v) * amount)).join(", ")})`;

/** Measures an element's content box, kept current. */
function useBox() {
  const ref = useRef(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    const measure = () => setBox(current => {
      const next = { width: Math.round(element.clientWidth), height: Math.round(element.clientHeight) };
      return next.width === current.width && next.height === current.height ? current : next;
    });
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, box];
}

// ---- the sketch ------------------------------------------------------------------------------

/** The generated app, drawn from its spec: same structure and colours as the real one. */
export function AppSketch({ spec, items = [], narrow = false }) {
  const tone = TONES[spec.theme] || TONES.midnight;
  const template = templateFor(spec.brief, spec.template);
  const copy = COPY[template] || COPY.checklist;
  const name = String(spec.name || "").trim() || "Your app";
  const brief = String(spec.brief || "").trim() || "Describe what it should help someone do, and the sketch follows as you type.";
  // Mixes are computed here, not with color-mix(), so the sketch paints the same in every engine.
  const style = {
    "--sk-glow": alpha(tone.accent, 0.17), "--sk-ring": alpha(tone.accent, 0.12), "--sk-field": mixHex(tone.panel, tone.page, 0.58), "--sk-row": mixHex(tone.panel, tone.page, 0.45),
    "--sk-hint": mixHex(tone.panel, tone.muted, 0.85),
    "--sk-page": tone.page, "--sk-panel": tone.panel, "--sk-strong": tone.panelStrong, "--sk-ink": tone.ink, "--sk-muted": tone.muted,
    "--sk-line": tone.line, "--sk-accent": tone.accent, "--sk-accent-ink": tone.accentInk,
  };
  return (
    <div className={`af-sketch${narrow ? " is-narrow" : ""}`} style={style} aria-hidden="true">
      <div className="af-sk-shell">
        <header className="af-sk-intro">
          <div>
            <span className="af-sk-eyebrow">LOCAL-FIRST · REVISION 1</span>
            <h1>{name}</h1>
            <p>{brief}</p>
          </div>
          <span className="af-sk-local"><i /> Saved on this device</span>
        </header>
        <section className="af-sk-work">
          <div className="af-sk-workhead">
            <div><span>FIRST USEFUL FLOW</span><h2>{copy.nouns[0].toUpperCase() + copy.nouns.slice(1)}</h2></div>
            <strong>{items.length} {copy.nouns}</strong>
          </div>
          <div className="af-sk-capture">
            <span className="af-sk-label">{copy.noun[0].toUpperCase() + copy.noun.slice(1)}</span>
            <div><span className="af-sk-input">{copy.placeholder}</span><span className="af-sk-button">{copy.verb}</span></div>
          </div>
          <div className="af-sk-toolbar">
            <span className="af-sk-input is-search">Filter locally…</span>
            <span className="af-sk-button is-secondary">Export JSON</span>
          </div>
          {items.length ? (
            <ol className="af-sk-list">
              {items.map((item, index) => (
                <li key={item}>
                  {template === "checklist" ? <i className={index === 0 ? "is-done" : ""} /> : null}
                  <span>{item}</span>
                  <small>{["just now", "12 min ago", "yesterday"][index] || "earlier"}</small>
                </li>
              ))}
            </ol>
          ) : (
            <div className="af-sk-empty"><strong>{copy.emptyTitle}</strong><p>{copy.emptyDetail}</p></div>
          )}
        </section>
        <footer className="af-sk-foot"><span>Generated by Neyvia App Factory</span><code>{name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "app"}</code></footer>
      </div>
    </div>
  );
}

// ---- the live app ----------------------------------------------------------------------------

/**
 * The real app in an iframe that never flashes: a new address (a rebuild, a reload) loads in a
 * second frame underneath and only crossfades in once it has painted; the old one then goes.
 */
export function LiveApp({ src, title, frameRef, width, height }) {
  const [frames, setFrames] = useState(() => (src ? [{ src, id: 0, ready: false }] : []));
  const next = useRef(1);
  useEffect(() => {
    setFrames(current => {
      if (!src) return [];
      if (current.length && current[current.length - 1].src === src) return current;
      return [...current.filter(frame => frame.ready).slice(-1), { src, id: next.current++, ready: false }];
    });
  }, [src]);
  const onLoad = id => setFrames(current => current.map(frame => (frame.id === id ? { ...frame, ready: true } : frame)));
  // Once the newest has painted, the ones under it leave after the crossfade.
  const newest = frames[frames.length - 1];
  useEffect(() => {
    if (!newest?.ready || frames.length < 2) return undefined;
    const timer = setTimeout(() => setFrames(current => current.filter(frame => frame.id === newest.id)), 360);
    return () => clearTimeout(timer);
  }, [newest?.id, newest?.ready, frames.length]);
  return (
    <div className="af-live">
      {frames.map(frame => (
        <iframe key={frame.id} ref={frame.id === newest?.id ? frameRef : undefined} src={frame.src} title={title} onLoad={() => onLoad(frame.id)}
          className={frame.ready ? "is-ready" : ""} style={{ width, height }} />
      ))}
      {newest && !newest.ready ? <span className="af-live-loading" role="status"><span className="af-shimmer" />Opening the app…</span> : null}
    </div>
  );
}

// ---- the frames ------------------------------------------------------------------------------

function WindowChrome({ title }) {
  return (
    <div className="af-chrome is-window" style={{ height: CHROME.window }}>
      <span className="af-chrome-app"><i />{title}</span>
      <span className="af-chrome-controls" aria-hidden="true"><Minus size={13} /><Square size={11} /><X size={14} /></span>
    </div>
  );
}

function BrowserChrome({ address }) {
  return (
    <div className="af-chrome is-browser" style={{ height: CHROME.browser }}>
      <span className="af-chrome-nav" aria-hidden="true"><ChevronLeft size={15} /><ChevronRight size={15} /><RotateCw size={13} /></span>
      <span className="af-chrome-address"><Lock size={11} aria-hidden="true" /><span>{address}</span></span>
      <span className="af-chrome-nav" aria-hidden="true"><Download size={14} /></span>
    </div>
  );
}

function PhoneStatus({ kind, light }) {
  return (
    <div className={`af-phone-status is-${kind}${light ? " is-light" : ""}`} aria-hidden="true">
      <span>9:41</span>
      <span><Signal size={kind === "iphone" ? 15 : 13} strokeWidth={2.4} /><Wifi size={kind === "iphone" ? 15 : 13} strokeWidth={2.4} /><BatteryFull size={kind === "iphone" ? 20 : 15} strokeWidth={2} /></span>
    </div>
  );
}

/**
 * The frame that fits the target, scaled to the space it has. `children` is the app drawn at the
 * frame's virtual size (a sketch, or LiveApp); `badge` floats on the frame's corner.
 */
export function TargetFrame({ kind, title, address, light = false, badge = null, working = false, children }) {
  const [ref, box] = useBox();
  const size = VIRTUAL[kind] || VIRTUAL.window;
  const phone = kind === "iphone" || kind === "android";
  const bezel = phone ? 12 : 0;
  const chrome = phone ? 0 : CHROME[kind] || 0;
  const outerWidth = size.width + bezel * 2;
  const outerHeight = size.height + bezel * 2;
  // Phones scale whole (bezel included). Windows keep a real-size title bar and scale the page.
  const scale = !box.width ? 0 : phone
    ? Math.min(1, (box.width - 8) / outerWidth, (box.height - 8) / outerHeight)
    : Math.min(1, (box.width - 8) / size.width, (box.height - 8 - chrome) / size.height);
  const content = typeof children === "function" ? children(size) : children;
  return (
    <div ref={ref} className="af-frame-space">
      {scale > 0 ? (
        phone ? (
          <div className={`af-device is-${kind}${working ? " is-working" : ""}`} style={{ width: outerWidth * scale, height: outerHeight * scale }}>
            <div className="af-device-body" style={{ width: outerWidth, height: outerHeight, transform: `scale(${scale})`, padding: bezel, borderRadius: kind === "iphone" ? 66 : 54 }}>
              <div className="af-device-screen" style={{ width: size.width, height: size.height, borderRadius: kind === "iphone" ? 55 : 44 }}>
                <div className="af-device-content" style={{ top: kind === "iphone" ? 54 : 40, bottom: kind === "iphone" ? 30 : 22 }}>{content}</div>
                <PhoneStatus kind={kind} light={light} />
                {kind === "iphone" ? <span className="af-device-island" /> : <span className="af-device-punch" />}
                <span className={`af-device-home${light ? " is-light" : ""}`} />
              </div>
            </div>
            {badge}
          </div>
        ) : (
          <div className={`af-window is-${kind}${working ? " is-working" : ""}`} style={{ width: size.width * scale, height: size.height * scale + chrome }}>
            {kind === "browser" ? <BrowserChrome address={address} /> : <WindowChrome title={title} />}
            <div className="af-window-page" style={{ height: size.height * scale }}>
              <div className="af-window-scaled" style={{ width: size.width, height: size.height, transform: `scale(${scale})` }}>{content}</div>
            </div>
            {badge}
          </div>
        )
      ) : null}
    </div>
  );
}

// ---- the build, flowing under the frame ------------------------------------------------------

const STAGE_LABELS = { brief: "Brief", scaffold: "Scaffold", assemble: "Assemble", verify: "Verify", register: "Register" };

/** The pipeline as one rail: done stages filled, the running one flowing, a failure stopping it. */
export function BuildRail({ job, building = false }) {
  const stages = useMemo(() => {
    const source = Array.isArray(job?.stages) && job.stages.length ? job.stages : Object.keys(STAGE_LABELS).map(id => ({ id, label: STAGE_LABELS[id], state: "pending" }));
    const rows = source.map(stage => ({ id: stage.id, label: stage.label || STAGE_LABELS[stage.id] || stage.id, state: stage.state || "pending", detail: stage.detail || "", ms: stage.durationMs }));
    // While the job is being made, the first stage not done yet is the one running.
    if (building && !rows.some(row => row.state === "running")) {
      const first = rows.find(row => row.state !== "completed");
      if (first) first.state = "running";
    }
    const native = job?.nativeBuild?.state;
    if (job?.spec?.target === "desktop") {
      rows.push({ id: "native", label: "Native build", state: native === "ready" ? "completed" : native === "failed" ? "failed" : ["queued", "running"].includes(native) ? "running" : "pending",
        detail: job?.nativeBuild?.error || "", ms: null });
    }
    return rows;
  }, [job, building]);
  const done = stages.filter(stage => stage.state === "completed").length;
  return (
    <ol className="af-rail" aria-label={`Build: ${done} of ${stages.length} stages done`}>
      {stages.map(stage => (
        <li key={stage.id} data-state={stage.state} title={stage.detail || undefined}>
          <span className="af-rail-dot" aria-hidden="true">
            {stage.state === "completed" ? <Check size={12} strokeWidth={2.6} /> : stage.state === "failed" ? <CircleAlert size={12} /> : stage.state === "running" ? <span className="af-rail-pulse" /> : <CircleDashed size={11} />}
          </span>
          <span className="af-rail-label">{stage.label}<span className="nx-visually-hidden">: {stage.state}</span></span>
          {stage.ms != null && stage.state === "completed" ? <small>{stage.ms < 1000 ? `${stage.ms} ms` : `${(stage.ms / 1000).toFixed(1)} s`}</small> : null}
        </li>
      ))}
    </ol>
  );
}
