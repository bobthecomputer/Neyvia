import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { FileCode, FolderOpen, RefreshCw, TriangleAlert } from "lucide-react";

import NeyviaMessageBody from "../NeyviaMessageBody.jsx";
import { parentOf, rawUrl } from "./nxDocsApi.js";
import { PaneMessage } from "./NxFilePane.jsx";
import { backendUrl, isUrl, panesCall } from "./nxPanesApi.js";
import { Button, Icon, IconButton, Spinner } from "./nxPrimitives.jsx";
import { os } from "./nxOsStore.js";
import { LocalOnlyGate } from "./NxLocalOnly.jsx";
import { OwnedBrowserPane } from "./NxBrowserPane.jsx";
import { ObserveDom, ObservedImage, PaneRefused, usePaneObservation } from "./NxPaneObserver.jsx";
import { POLL_MS, initialWatch, liveLabel, tick } from "./nxLiveModel.js";
import "./nxPanes.css";

// pane.show {kind: "artifact"}: what an agent produced, shown for real. HTML
// runs in a sandboxed page with no access to Neyvia (its own token, an opaque
// origin; files next to it load too), Markdown is rendered, images and PDFs
// open in place. When the agent rewrites the file, the view follows.

const NxPdfApp = lazy(() => import("./NxPdfApp.jsx").then(module => ({ default: module.NxPdfApp })));
const isImage = value => /\.(png|jpe?g|gif|webp|svg|avif|bmp|ico)(\?|$)/i.test(String(value || ""));
const KIND_LABEL = { html: "Web page", markdown: "Markdown", image: "Image", pdf: "PDF", text: "Text" };

// A web address is a page: it opens in a tab Neyvia owns (NxBrowserPane), never in a loose iframe.
function UrlArtifact({ target }) {
  if (isImage(target)) return <LocalOnlyGate url={target}><div className="nx-pane-image"><ObservedImage src={target} alt={target} runtime={`image:${target.slice(0, 100)}`} /></div></LocalOnlyGate>;
  return <LocalOnlyGate url={target}><OwnedBrowserPane target={target} /></LocalOnlyGate>;
}

/**
 * The sandboxed HTML page, reported once the frame has loaded. Its origin is opaque by design, so
 * the projection is the page source it loaded, read again from the same artifact address.
 */
function ArtifactFrame({ artifact, version }) {
  const observation = usePaneObservation();
  const src = backendUrl(artifact.url);
  const onLoad = async () => {
    try {
      const response = await fetch(src, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await observation.report({ runtimeId: `artifact-frame:${artifact.name}:${artifact.modified ?? ""}:${version}`.slice(0, 128), content: await response.text() });
    } catch (error) { observation.fail(`The page loaded but couldn't be read back: ${error.message}`); }
  };
  // The server sends the page with a CSP sandbox (opaque origin, no top navigation), so the
  // frame needs no sandbox attribute of its own; some embedded browsers refuse that attribute.
  return <iframe key={version} className="nx-ap-frame" title={artifact.name} src={src} referrerPolicy="no-referrer" onLoad={() => void onLoad()} />;
}

/** Text the pane displays (Markdown source rendered, or plain text), reported as shown. */
function ReportText({ artifact }) {
  const observation = usePaneObservation();
  useEffect(() => {
    void observation.report({ runtimeId: `artifact-${artifact.kind}:${artifact.name}:${artifact.modified ?? ""}`.slice(0, 128), content: artifact.text || "" });
  }, [observation, artifact.kind, artifact.name, artifact.modified, artifact.text]);
  return null;
}

/**
 * A page that swaps to its next version only once that version has loaded, so edits never flash white.
 * Two fixed frames: the visible one stays untouched while the hidden one loads the new version, then
 * they trade places (no remount, so the page being shown is never reloaded twice).
 */
function LiveFrame({ src, title }) {
  const [slots, setSlots] = useState([src, null]);
  const [active, setActive] = useState(0);
  const pending = useRef(-1);
  useEffect(() => {
    if (slots[active] === src) return;
    const next = 1 - active;
    pending.current = next;
    setSlots(current => current.map((value, index) => (index === next ? src : value)));
  }, [src, active, slots]);
  const loaded = index => {
    if (pending.current === index && slots[index] === src) { pending.current = -1; setActive(index); }
  };
  return (
    <div className="nx-ap-live">
      {slots.map((value, index) => (value ? (
        <iframe key={index} className={`nx-ap-frame${index === active ? "" : " nx-ap-frame-back"}`} title={index === active ? title : `${title} (updating)`}
          src={value} referrerPolicy="no-referrer" data-live={index === active ? "front" : "back"} aria-hidden={index === active ? undefined : "true"}
          tabIndex={index === active ? undefined : -1} onLoad={() => loaded(index)} />
      ) : null))}
    </div>
  );
}

export function NxArtifactPane({ target }) {
  const [artifact, setArtifact] = useState({ status: "loading" });
  const [version, setVersion] = useState(0);
  const [updatedAt, setUpdatedAt] = useState(null);
  const [, setClock] = useState(0);
  const modified = useRef(null);
  const marker = useRef(null);

  const load = useCallback(async quiet => {
    try {
      const data = await panesCall("artifact.open", { path: target });
      modified.current = data.modified;
      if (!quiet && data.version) marker.current = initialWatch(data.version);
      setArtifact({ status: "ready", ...data });
      if (quiet) { setVersion(value => value + 1); setUpdatedAt(Date.now()); }
    } catch (error) {
      if (!quiet) setArtifact({ status: "error", error: error.message, missing: error.status === 404 });
    }
  }, [target]);

  useEffect(() => {
    if (!target || isUrl(target)) return undefined;
    setArtifact({ status: "loading" });
    modified.current = null;
    marker.current = null;
    setUpdatedAt(null);
    void load(false);
    // Follow the file while it is open: an agent often rewrites its output. A cheap marker is read
    // about once a second; a change is shown once it holds still (nxLiveModel), without flashing.
    let alive = true;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy || document.visibilityState !== "visible") return;
      busy = true;
      try {
        const stat = await panesCall("artifact.stat", { path: target });
        if (!alive) return;
        if (marker.current == null) { marker.current = initialWatch(stat.version); return; }
        const step = tick(marker.current, stat.version);
        marker.current = step.watch;
        if (step.reload) await load(true);
      } catch { /* the next tick tries again */ } finally { busy = false; }
    }, POLL_MS);
    const clock = setInterval(() => setClock(value => value + 1), 5000);
    return () => { alive = false; clearInterval(timer); clearInterval(clock); };
  }, [target, load]);

  if (isUrl(target)) return <UrlArtifact target={target} />;
  if (!target) return <PaneMessage title="No artifact chosen"><PaneRefused reason="No artifact chosen" />An agent shows its output here: a web page, Markdown, an image or a PDF.</PaneMessage>;
  if (artifact.status === "loading") return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (artifact.status === "error") {
    return (
      <PaneMessage icon={TriangleAlert} title={artifact.missing ? "Artifact not found" : "This artifact can't be shown"}
        action={<Button size="sm" onClick={() => void load(false)}>Try again</Button>}><PaneRefused reason={artifact.error} />{artifact.error}</PaneMessage>
    );
  }
  const { kind } = artifact;
  return (
    <div className="nx-ap">
      <div className="nx-fp-bar">
        <Icon as={FileCode} size={15} />
        <span className="nx-fp-name" title={artifact.path}>{artifact.name}</span>
        <span className="nx-fp-chip">{KIND_LABEL[kind] || "File"}</span>
        <span className="nx-fp-chip nx-ap-livechip" role="status" aria-live="off" title="This view follows the file while an agent edits it">{liveLabel(updatedAt)}</span>
        <span className="nx-head-spacer" />
        <IconButton size="sm" icon={RefreshCw} label="Reload" onClick={() => { setVersion(value => value + 1); void load(false); }} />
        {kind === "html" || kind === "markdown" || kind === "text" ? <Button size="sm" onClick={() => os.showPane("file", artifact.path)}>Edit source</Button> : null}
        <IconButton size="sm" icon={FolderOpen} label="Show in Files" onClick={() => os.openApp("files", "documents", parentOf(artifact.path))} />
      </div>
      {kind === "html" ? (
        <ArtifactFrame artifact={artifact} version={version} />
      ) : kind === "markdown" ? (
        <div className="nx-ap-doc nx-scroll"><ReportText artifact={artifact} /><div className="nx-ap-prose"><NeyviaMessageBody text={artifact.text} /></div></div>
      ) : kind === "image" ? (
        <div className="nx-pane-image"><ObservedImage key={version} src={`${rawUrl(artifact.path)}&v=${version}`} alt={artifact.name} runtime={`image:${artifact.name}:${version}`.slice(0, 128)} /></div>
      ) : kind === "pdf" ? (
        <Suspense fallback={<div className="nx-stage-loading"><Spinner size={16} /></div>}><ObserveDom /><NxPdfApp key={version} target={artifact.path} /></Suspense>
      ) : kind === "text" ? (
        <pre className="nx-ap-text nx-scroll"><ReportText artifact={artifact} />{artifact.text}</pre>
      ) : (
        <PaneMessage title={artifact.name}><PaneRefused reason={artifact.reason || "This artifact can't be shown"} />{artifact.reason}</PaneMessage>
      )}
    </div>
  );
}
