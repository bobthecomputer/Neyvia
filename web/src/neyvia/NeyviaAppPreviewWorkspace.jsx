import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Bot, ExternalLink, RefreshCw } from "lucide-react";
import { APP_FACTORY_COMMANDS, appFactoryJobPayload } from "./neyviaAppFactoryModel.js";
import { NeyviaTasteReview } from "./NeyviaTasteReview.jsx";
import "./neyviaAppPreviewWorkspace.css";
import "./neyviaAppFactoryStudio.css";
import { AppSketch, FRAMES, LiveApp, SAMPLE, TargetFrame, frameForTarget } from "./NeyviaAppFactoryCanvas.jsx";

// Review the built files directly: the served preview needs a Neyvia session.
function appBuildFileUrl(projectRoot) {
  const root = String(projectRoot || "").trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return root ? `file:///${root.replace(/^\/+/, "")}/dist/index.html` : "";
}

const ACTIVE_JOB_KEY = "neyvia.appFactory.activeJob.v1";

export function rememberAppFactoryJob(jobId, root = "") {
  if (!jobId || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ jobId, root }));
  } catch {
    // A live request still opens Preview when storage is unavailable.
  }
}

function recalledAppFactoryJob() {
  try {
    return JSON.parse(window.localStorage.getItem(ACTIVE_JOB_KEY) || "null") || {};
  } catch {
    return {};
  }
}

function appPreviewUrl(value) {
  const source = String(value || "").trim();
  if (!/^\/api\/app-factory\/[a-zA-Z0-9_-]+\//.test(source)) return "";
  const backend = String(import.meta.env?.VITE_FLUXIO_BACKEND_URL || window.__FLUXIO_BACKEND_URL__ || "")
    .trim().replace(/\/$/, "");
  return `${backend}${source}`;
}

export function NeyviaAppPreviewWorkspace({ callBackend, onRequestAction, onSetSurface, previewRequest, workspaceRoot = "" }) {
  const [selection, setSelection] = useState(() => recalledAppFactoryJob());
  const [job, setJob] = useState(null);
  const [catalog, setCatalog] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [testing, setTesting] = useState(false);
  const requestedId = String(previewRequest?.jobId || "").trim();
  const selectedId = String(selection.jobId || requestedId || "").trim();
  const root = String(previewRequest?.root || selection.root || workspaceRoot || "").trim();

  useEffect(() => {
    if (!requestedId) return;
    const next = { jobId: requestedId, root: String(previewRequest?.root || workspaceRoot || "").trim() };
    rememberAppFactoryJob(next.jobId, next.root);
    setSelection(next);
  }, [previewRequest, requestedId, workspaceRoot]);

  const refresh = useCallback(async () => {
    if (typeof callBackend !== "function") return;
    setLoading(true);
    setError("");
    try {
      const options = { throwOnError: true };
      const payload = root ? { root } : {};
      const listing = await callBackend(APP_FACTORY_COMMANDS.catalog, payload, options);
      const jobs = Array.isArray(listing?.jobs) ? listing.jobs : [];
      setCatalog(jobs);
      const activeId = selectedId || String(jobs[0]?.jobId || "");
      if (activeId) {
        const active = await callBackend(APP_FACTORY_COMMANDS.getJob, appFactoryJobPayload(activeId, root), options);
        setJob(active);
        if (activeId !== selectedId) {
          setSelection({ jobId: activeId, root });
          rememberAppFactoryJob(activeId, root);
        }
      } else {
        setJob(null);
      }
    } catch (caught) {
      setJob(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [callBackend, root, selectedId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const previewUrl = appPreviewUrl(job?.previewUrl);
  const staticPassed = job?.verification?.state === "passed";
  const runtimePassed = job?.verification?.runtimeVerified === true;
  const current = job?.jobId === selectedId || (!selectedId && job);
  const visiblePreview = Boolean(current && staticPassed && previewUrl);
  const nativeBuild = job?.nativeBuild || {};
  const canRunStarterJourney = staticPassed && ["notes", "checklist"].includes(job?.spec?.template);
  const testApp = async () => {
    if (!job?.jobId || !canRunStarterJourney || testing) return;
    setTesting(true);
    setError("");
    try {
      const result = await callBackend(APP_FACTORY_COMMANDS.testJob,
        appFactoryJobPayload(job.jobId, root), { throwOnError: true });
      setJob(result.job);
      setReloadKey(value => value + 1);
      if (result.job?.verification?.runtimeVerified !== true) setError(`The saved journey failed: ${result.cleanupRun?.status || result.run?.status || "effect unverified"}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setTesting(false);
    }
  };

  const [frameChoice, setFrameChoice] = useState(null);
  const target = job?.capabilityHandoff ? "neyvia" : job?.spec?.target || "neyvia";
  const frame = frameChoice || frameForTarget(target);
  const liveSrc = visiblePreview ? `${previewUrl}${reloadKey ? `${previewUrl.includes("?") ? "&" : "?"}r=${reloadKey}` : ""}` : "";
  const appName = current ? job?.spec?.name || "App Preview" : "App Preview";
  const sketch = job && current ? { name: job.spec?.name, brief: job.spec?.brief, template: job.spec?.template, theme: job.spec?.theme || "midnight" } : SAMPLE;
  const badge = visiblePreview
    ? { tone: "live", label: runtimePassed ? "Live · journey passed" : "Live · checks passed" }
    : loading ? { tone: "sketch", label: "Loading…" } : job ? { tone: "danger", label: "Needs a current build" } : { tone: "sample", label: "Sample" };

  return (
    <section className="neyvia-app-preview" data-app-preview-workspace="true">
      <header className="neyvia-app-preview-head">
        <div className="neyvia-app-preview-title">
          <button type="button" aria-label="Back to App Factory" title="Back to App Factory" onClick={() => onSetSurface?.("app-factory")}><ArrowLeft size={17} /></button>
          <div><span>PREVIEW</span><h1>{appName}</h1></div>
        </div>
        <div className="neyvia-app-preview-actions">
          <label htmlFor="neyvia-preview-job" className="nx-visually-hidden">App</label>
          <select id="neyvia-preview-job" value={selectedId} onChange={event => {
            const jobId = event.target.value;
            setSelection({ jobId, root });
            rememberAppFactoryJob(jobId, root);
          }}>
            {!selectedId && <option value="">Choose an app</option>}
            {catalog.map(item => <option key={item.jobId} value={item.jobId}>{item.spec?.name || item.jobId}</option>)}
          </select>
          <button type="button" aria-label="Refresh" title="Refresh" onClick={() => { setReloadKey(value => value + 1); void refresh(); }} disabled={loading}><RefreshCw size={15} /></button>
          {previewUrl && <a href={previewUrl} target="_blank" rel="noopener noreferrer" aria-label="Open in a new tab" title="Open in a new tab"><ExternalLink size={15} /></a>}
        </div>
      </header>

      {error && <p className="neyvia-app-preview-error" role="alert">{error}</p>}

      <div className="neyvia-app-preview-canvas">
        <div className="neyvia-app-preview-frames" role="radiogroup" aria-label="Show the app in">
          {FRAMES.map(item => (
            <button key={item.id} type="button" role="radio" aria-checked={frame === item.id} className={frame === item.id ? "is-on" : ""}
              onClick={() => setFrameChoice(item.id === frameForTarget(target) ? null : item.id)}>{item.label}</button>
          ))}
        </div>
        {/* No app yet: a banner above the frame, never a card over the sample's rows. */}
        {!visiblePreview && !loading ? (
          <div className="neyvia-app-preview-empty" role="status">
            <div>
              <strong>{job ? "This app needs a current build" : "Make an app to see it here"}</strong>
              <p>{job ? "Go back to App Factory and continue after the latest change." : "Below is a sample. Make an app in App Factory and it runs here, in a frame that fits it."}</p>
            </div>
            <button type="button" className="is-accent" onClick={() => onSetSurface?.("app-factory")}>Open App Factory</button>
          </div>
        ) : null}
        <div className="neyvia-app-preview-stage">
          <TargetFrame kind={frame} title={appName} address={visiblePreview ? `localhost${String(job?.previewUrl || "").split("?")[0]}` : "localhost/apps/preview"}
            light={(sketch.theme || "midnight") === "paper"} working={loading || testing}
            badge={<span className="af-badge" data-tone={badge.tone}><i />{badge.label}</span>}>
            {size => (
              <div className="af-crossfade" key={visiblePreview ? `live:${job.jobId}` : job ? `job:${job.jobId}` : "sample"}>
                {visiblePreview
                  ? <LiveApp src={liveSrc} title={`${job.spec?.name || "Generated app"} interactive preview`} width={size.width} height={size.height - (frame === "iphone" ? 84 : frame === "android" ? 62 : 0)} />
                  : <AppSketch spec={sketch} items={job ? [] : SAMPLE.items} narrow={frame === "iphone" || frame === "android"} />}
              </div>
            )}
          </TargetFrame>
        </div>
      </div>

      {current && (
        <div className="neyvia-app-preview-truth" aria-label="Build and test state">
          <span data-preview-static={staticPassed ? "passed" : "pending"}><i />Source and package: {staticPassed ? "checked" : "needs checking"}</span>
          <span data-preview-runtime={runtimePassed ? "passed" : "unverified"}><i />App behavior: {runtimePassed ? "journey verified" : "not yet tested"}</span>
          <span data-preview-native={nativeBuild.state || "pending"}><i />Windows build: {nativeBuild.state === "ready" ? "compiled; launch unverified" : nativeBuild.state || "not built"}</span>
          <span className="neyvia-app-preview-spacer" />
          {canRunStarterJourney && <button type="button" onClick={() => void testApp()} disabled={testing}>{testing ? "Testing…" : "Test app"}</button>}
          <button type="button" className="is-accent" onClick={() => onRequestAction?.("app-factory:continue-agent", {
            jobId: job.jobId, projectRoot: job.projectRoot, previewUrl: job.previewUrl, prompt: job.agentHandoff?.prompt,
          })}><Bot size={15} /> Improve with Agent</button>
        </div>
      )}

      {visiblePreview ? (
        <details className="neyvia-app-preview-review">
          <summary>Taste review</summary>
          <NeyviaTasteReview callBackend={callBackend} goal={job.spec?.brief || ""} key={`${job.jobId}-${job.updatedAt}`}
            savedJourney={runtimePassed ? job.verification?.runtimeProof : null} url={appBuildFileUrl(job.projectRoot)} />
        </details>
      ) : null}
    </section>
  );
}
