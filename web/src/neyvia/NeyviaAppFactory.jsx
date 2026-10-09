import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePoller } from "./usePoller.js";
import {
  AppWindow,
  ArrowRight,
  Bot,
  Box,
  Check,
  ChevronLeft,
  CircleAlert,
  Code2,
  ExternalLink,
  FolderTree,
  Hammer,
  LoaderCircle,
  PackageCheck,
  Play,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Smartphone,
  Sparkles,
} from "lucide-react";

import {
  APP_FACTORY_COMMANDS,
  appFactoryCapabilityPayload,
  appFactoryCreatePayload,
  appFactoryEligibleHandoffs,
  appFactoryHandoffForJob,
  appFactoryJobPayload,
  appFactoryJobTone,
  appFactoryOutcomeImportPayload,
  appFactoryProgress,
  compactFactoryHash,
  normalizeAppFactoryCatalog,
} from "./neyviaAppFactoryModel.js";
import "./neyviaAppFactory.css";
import "./neyviaAppFactoryStudio.css";
import { AppSketch, BuildRail, FRAMES, LiveApp, SAMPLE, TargetFrame, frameForTarget } from "./NeyviaAppFactoryCanvas.jsx";
import { rememberAppFactoryJob } from "./NeyviaAppPreviewWorkspace.jsx";

const EMPTY_FORM = Object.freeze({
  name: "",
  brief: "",
  target: "desktop",
  template: "auto",
  theme: "midnight",
  directory: "",
});

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "Not recorded";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function readableDate(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

/** The backend origin a relative preview address is served from (the same origin when empty). */
function previewOrigin(url) {
  if (!String(url || "").startsWith("/")) return "";
  return String(import.meta.env?.VITE_FLUXIO_BACKEND_URL || window.__FLUXIO_BACKEND_URL__ || "").trim().replace(/\/$/, "");
}

function Receipt({ icon: Icon, label, value, detail, tone = "neutral" }) {
  return (
    <article className="neyvia-factory-receipt" data-tone={tone}>
      <Icon aria-hidden="true" size={17} />
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

export function NeyviaAppFactory({
  callBackend,
  onOpenPanel,
  onRequestAction,
  onSetSurface,
  workspaceRoot = "",
}) {
  const [catalog, setCatalog] = useState(() => normalizeAppFactoryCatalog({}));
  const [selectedJobId, setSelectedJobId] = useState("");
  const [selectedJob, setSelectedJob] = useState(null);
  const [selectedHandoffId, setSelectedHandoffId] = useState("");
  const [handoffReviewConfirmed, setHandoffReviewConfirmed] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pollRef = useRef(null);
  const previewRef = useRef(null);
  const outcomeImportRef = useRef(false);
  const [frameChoice, setFrameChoice] = useState(null);
  const [compactPane, setCompactPane] = useState("brief");
  const [reloadKey, setReloadKey] = useState(0);

  const invoke = useCallback(
    async (command, payload = {}) => {
      if (typeof callBackend !== "function") {
        throw new Error("The App Factory backend is unavailable.");
      }
      return callBackend(command, payload, { throwOnError: true });
    },
    [callBackend],
  );

  const refreshCatalog = useCallback(
    async ({ selectFirst = false, silent = false } = {}) => {
      if (!silent) setLoading(true);
      setError("");
      try {
        const payload = workspaceRoot ? { root: workspaceRoot } : {};
        const next = normalizeAppFactoryCatalog(
          await invoke(APP_FACTORY_COMMANDS.catalog, payload),
        );
        setCatalog(next);
        const nextId =
          selectedJobId ||
          (selectFirst ? String(next.jobs[0]?.jobId || "") : "");
        if (nextId) {
          const nextJob = next.jobs.find(job => job.jobId === nextId);
          if (nextJob) {
            setSelectedJob(nextJob);
            setSelectedJobId(nextId);
          }
        }
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [invoke, selectedJobId, workspaceRoot],
  );

  const refreshJob = useCallback(
    async (jobId = selectedJobId, { silent = false } = {}) => {
      if (!jobId) return null;
      if (!silent) setBusyAction("refresh");
      try {
        const job = await invoke(
          APP_FACTORY_COMMANDS.getJob,
          appFactoryJobPayload(jobId, workspaceRoot),
        );
        setSelectedJob(job);
        setCatalog(current =>
          normalizeAppFactoryCatalog({
            ...current,
            jobs: current.jobs.map(item => (item.jobId === job.jobId ? job : item)),
          }),
        );
        return job;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        return null;
      } finally {
        if (!silent) setBusyAction("");
      }
    },
    [invoke, selectedJobId, workspaceRoot],
  );

  useEffect(() => {
    void refreshCatalog({ selectFirst: true });
  }, [refreshCatalog]);

  // A native build is followed at 1.4 s, backing off to 10 s if it reports nothing new; hidden pages are skipped.
  usePoller(async () => {
    const job = await refreshJob(selectedJob.jobId, { silent: true });
    return job?.nativeBuild ?? null; // unchanged build state is what lets the poll slow down
  }, {
    enabled: ["queued", "running"].includes(String(selectedJob?.nativeBuild?.state || "")),
    activeMs: 1400, maxMs: 10000, pollerRef: pollRef,
  });

  const runAction = async (action, task) => {
    setBusyAction(action);
    setError("");
    setNotice("");
    try {
      return await task();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return null;
    } finally {
      setBusyAction("");
    }
  };

  useEffect(() => {
    const receiveCapabilityOutcomes = async event => {
      if (
        event.source !== previewRef.current?.contentWindow
        || event.origin !== window.location.origin
        || event.data?.type !== "neyvia:capability-run-bundle:v2"
      ) {
        return;
      }
      const payload = appFactoryOutcomeImportPayload(
        event.data?.bundle,
        workspaceRoot,
      );
      if (!payload) {
        setError("The generated app returned an invalid outcome bundle.");
        return;
      }
      if (outcomeImportRef.current) return;
      outcomeImportRef.current = true;
      setBusyAction("import-outcomes");
      setError("");
      setNotice("");
      try {
        const result = await invoke(APP_FACTORY_COMMANDS.importOutcomes, payload);
        const imported = Number(result?.importedRunCount || 0);
        const duplicates = Number(result?.duplicateRunCount || 0);
        const patterns = Number(result?.frictionPatternCount || 0);
        setNotice(
          `${imported} typed ${imported === 1 ? "outcome" : "outcomes"} verified`
          + `${duplicates ? ` · ${duplicates} already known` : ""}`
          + `${patterns ? ` · ${patterns} repeated friction ${patterns === 1 ? "pattern" : "patterns"} ready for review` : " · no repeated pattern yet"}.`,
        );
        onRequestAction?.("capability-evolution:app-outcomes-imported", result);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        outcomeImportRef.current = false;
        setBusyAction("");
      }
    };
    window.addEventListener("message", receiveCapabilityOutcomes);
    return () => window.removeEventListener("message", receiveCapabilityOutcomes);
  }, [invoke, onRequestAction, workspaceRoot]);

  const createJob = async event => {
    event.preventDefault();
    const selectedHandoff = catalog.capabilityHandoffs.find(
      item => item.handoffId === selectedHandoffId,
    );
    const capabilityPayload = selectedHandoff
      ? appFactoryCapabilityPayload(
        selectedHandoff,
        form,
        workspaceRoot,
        handoffReviewConfirmed,
      )
      : null;
    if (selectedHandoff && !capabilityPayload) {
      setError("Review and confirm the exact inactive source before shaping this app.");
      return;
    }
    const job = await runAction("create", () =>
      invoke(
        selectedHandoff
          ? APP_FACTORY_COMMANDS.createFromCapability
          : APP_FACTORY_COMMANDS.create,
        selectedHandoff
          ? capabilityPayload
          : appFactoryCreatePayload(form, workspaceRoot),
      ),
    );
    if (!job) return;
    setSelectedJob(job);
    setSelectedJobId(job.jobId);
    rememberAppFactoryJob(job.jobId, workspaceRoot);
    setNotice(`${job.spec?.name || "The app"} has a local preview. Test its behavior before relying on it.`);
    setForm(EMPTY_FORM);
    setSelectedHandoffId("");
    setHandoffReviewConfirmed(false);
    await refreshCatalog({ silent: true });
  };

  const resumeJob = async () => {
    if (!selectedJob?.jobId) return;
    const job = await runAction("resume", () =>
      invoke(
        APP_FACTORY_COMMANDS.resume,
        appFactoryJobPayload(selectedJob.jobId, workspaceRoot),
      ),
    );
    if (job) {
      setSelectedJob(job);
      setNotice("The pipeline resumed from its last verified stage.");
      await refreshCatalog({ silent: true });
    }
  };

  const buildNative = async () => {
    if (!selectedJob?.jobId) return;
    const job = await runAction("native", () =>
      invoke(
        APP_FACTORY_COMMANDS.buildNative,
        appFactoryJobPayload(selectedJob.jobId, workspaceRoot),
      ),
    );
    if (job) {
      setSelectedJob(job);
      setNotice("Native compilation started. Neyvia will keep the receipt here.");
    }
  };

  const testJob = async () => {
    if (!selectedJob?.jobId) return;
    const result = await runAction("test", () => invoke(
      APP_FACTORY_COMMANDS.testJob,
      appFactoryJobPayload(selectedJob.jobId, workspaceRoot),
    ));
    if (!result) return;
    setSelectedJob(result.job);
    setNotice(result.job?.verification?.runtimeVerified
      ? "Saved journeys passed: add, reload, remove, and reload again."
      : `Saved journey failed at ${result.cleanupRun?.status || result.run?.status || "an unverified step"}. Review and repair the app.`);
  };

  const installNative = async () => {
    if (!selectedJob?.jobId) return;
    const job = await runAction("install", () => invoke(
      APP_FACTORY_COMMANDS.installNative,
      appFactoryJobPayload(selectedJob.jobId, workspaceRoot),
    ));
    if (job) {
      setSelectedJob(job);
      setNotice("The exact tested Windows build is installed for this user. Its previous revision remains available for rollback.");
    }
  };

  const rollbackNative = async () => {
    if (!selectedJob?.jobId) return;
    const job = await runAction("rollback", () => invoke(
      APP_FACTORY_COMMANDS.rollbackNative,
      appFactoryJobPayload(selectedJob.jobId, workspaceRoot),
    ));
    if (job) {
      setSelectedJob(job);
      setNotice("The Start Menu shortcut now points to the previous intact revision.");
    }
  };

  const selectJob = job => {
    setSelectedJobId(job.jobId);
    setSelectedJob(job);
    rememberAppFactoryJob(job.jobId, workspaceRoot);
    setError("");
    setNotice("");
  };

  const selectHandoff = handoff => {
    const suggested = handoff?.suggestedApp || {};
    setSelectedHandoffId(String(handoff?.handoffId || ""));
    setHandoffReviewConfirmed(false);
    setForm({
      name: String(suggested.name || handoff?.label || ""),
      brief: String(suggested.brief || ""),
      target: String(suggested.target || "neyvia"),
      template: "capability",
      theme: String(suggested.theme || "midnight"),
      directory: String(suggested.directory || ""),
    });
    setError("");
    setNotice("");
  };

  const clearHandoff = () => {
    setSelectedHandoffId("");
    setHandoffReviewConfirmed(false);
    setForm(EMPTY_FORM);
  };

  const progress = appFactoryProgress(selectedJob);
  const tone = appFactoryJobTone(selectedJob);
  const nativeBuild = selectedJob?.nativeBuild || {};
  const installation = selectedJob?.installation || {};
  const nativeBusy = ["queued", "running"].includes(nativeBuild.state);
  const packageReceipt = selectedJob?.package || {};
  const previewUrl = String(selectedJob?.previewUrl || "");
  const verified = selectedJob?.verification?.state === "passed";
  const canBuildNative =
    selectedJob?.spec?.target === "desktop" &&
    verified &&
    !nativeBusy &&
    nativeBuild.state !== "ready";
  const canInstallNative = nativeBuild.state === "ready" && selectedJob?.verification?.runtimeVerified === true
    && ["not_installed", "update_available"].includes(installation.state);
  const selectedTarget = useMemo(
    () => catalog.targets.find(target => target.id === form.target),
    [catalog.targets, form.target],
  );
  const eligibleHandoffs = useMemo(
    () => appFactoryEligibleHandoffs(catalog),
    [catalog],
  );
  const selectedHandoff = useMemo(
    () => catalog.capabilityHandoffs.find(
      item => item.handoffId === selectedHandoffId,
    ) || null,
    [catalog.capabilityHandoffs, selectedHandoffId],
  );
  const selectedJobHandoffReview = useMemo(
    () => appFactoryHandoffForJob(catalog, selectedJob),
    [catalog, selectedJob],
  );
  const selectedJobHandoff = selectedJob?.capabilityHandoff || null;
  const displayWorkspaceRoot = String(workspaceRoot || catalog.workspaceRoot || "");
  const workspaceName = displayWorkspaceRoot
    .replace(/[\\/]+$/, "")
    .split(/[\\/]/)
    .pop() || "Current workspace";

  // ---- what the canvas shows -------------------------------------------------------------
  // A selected job shows its real app once the checks pass, and a sketch of its brief until then.
  // With no job, the form's brief is sketched as you type; an empty form shows a sample.
  const typing = Boolean(form.name.trim() || form.brief.trim());
  const sketchSpec = selectedJob
    ? { name: selectedJob.spec?.name, brief: selectedJob.spec?.brief, template: selectedJob.spec?.template, theme: selectedJob.spec?.theme || "midnight" }
    : typing ? { name: form.name, brief: form.brief, template: form.template, theme: form.theme } : SAMPLE;
  const target = selectedJob ? (selectedJob.capabilityHandoff ? "neyvia" : selectedJob.spec?.target || "desktop") : form.target;
  const frame = frameChoice || frameForTarget(target);
  const live = Boolean(selectedJob && verified && previewUrl);
  const building = busyAction === "create" || busyAction === "resume" || tone === "working";
  const liveSrc = live ? `${previewOrigin(previewUrl)}${previewUrl}${reloadKey ? `${previewUrl.includes("?") ? "&" : "?"}r=${reloadKey}` : ""}` : "";
  const appTitle = String(sketchSpec.name || "").trim() || "Your app";
  const status = live
    ? { tone: "live", label: selectedJob.verification?.runtimeVerified ? "Live · journey passed" : "Live · checks passed" }
    : selectedJob
      ? { tone: tone === "danger" ? "danger" : "sketch", label: tone === "danger" ? "Stopped · sketch of the brief" : building ? `Building · ${progress.completed} of ${progress.total}` : "Sketch · waiting for checks" }
      : building ? { tone: "sketch", label: "Building…" } : typing ? { tone: "sketch", label: "Sketch of your brief" } : { tone: "sample", label: "Sample" };
  const caption = live
    ? "This is the built app, running. Use it right here; every rebuild slides in without a reload flash."
    : selectedJob
      ? "The real app replaces this sketch as soon as its source, package and contract checks pass."
      : typing
        ? form.target === "ios-studio" ? "iPhone and iPad apps are built in iOS Studio, which keeps its own Apple proof gates." : "The sketch follows your brief as you type. Make the app to build the real one."
        : "A sample of what App Factory makes. Give yours a name and a task, and it takes shape here.";
  const sketchItems = !selectedJob && !typing ? SAMPLE.items : [];
  const sketchLight = (sketchSpec.theme || "midnight") === "paper";
  const newApp = () => { setSelectedJob(null); setSelectedJobId(""); setError(""); setNotice(""); setFrameChoice(null); setCompactPane("brief"); };

  const preview = (
    <TargetFrame
      kind={frame}
      title={appTitle}
      address={live ? `localhost${previewUrl.split("?")[0]}` : `localhost/apps/${appTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "app"}`}
      light={sketchLight}
      working={building}
      badge={<span className="af-badge" data-tone={status.tone}><i />{status.label}</span>}
    >
      {size => (
        <div className="af-crossfade" key={live ? `live:${selectedJob.jobId}` : selectedJob ? `job:${selectedJob.jobId}` : typing ? "brief" : "sample"}
          data-nx-comment-target={`app-factory:${appTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "app"}`} data-nx-comment-kind="dom" data-nx-comment-label={`${appTitle} preview`}>
          {live
            ? <LiveApp src={liveSrc} title={`${selectedJob.spec?.name || "Generated app"} preview`} frameRef={previewRef} width={size.width} height={size.height - (frame === "iphone" ? 84 : frame === "android" ? 62 : 0)} />
            : <AppSketch spec={sketchSpec} items={sketchItems} narrow={frame === "iphone" || frame === "android"} />}
        </div>
      )}
    </TargetFrame>
  );

  return (
    <section className="neyvia-app-factory af" data-app-factory="true" data-af-pane={compactPane}>
      <header className="af-head">
        <button aria-label="Back to agent" className="af-iconbtn af-back" onClick={() => onSetSurface?.("agent")} type="button">
          <ChevronLeft aria-hidden="true" size={17} />
        </button>
        <div className="af-mark"><Sparkles aria-hidden="true" size={18} /></div>
        <div className="af-title">
          <span className="af-eyebrow">APP FACTORY</span>
          <h1>{selectedJob || typing ? appTitle : "Make an app"}</h1>
        </div>
        <div className="af-head-tools">
          <div className="af-seg" role="radiogroup" aria-label="Show the app in">
            {FRAMES.map(item => (
              <button key={item.id} type="button" role="radio" aria-checked={frame === item.id} className={frame === item.id ? "is-on" : ""}
                onClick={() => setFrameChoice(item.id === frameForTarget(target) ? null : item.id)}>{item.label}</button>
            ))}
          </div>
          {installation.state === "update_available" ? <button className="af-button" onClick={() => void installNative()} disabled={Boolean(busyAction)} type="button">Update app</button> : null}
          {selectedJob ? <button className="af-button" onClick={newApp} type="button"><Sparkles aria-hidden="true" size={14} /> New app</button> : null}
        </div>
      </header>


      <div className="af-body">
        <main className="af-canvas" aria-label="The app being made">
          {error ? <div className="af-message" data-tone="danger" role="alert"><CircleAlert size={15} />{error}</div> : null}
          {notice ? <div className="af-message" data-tone="ready" role="status"><Check size={15} />{notice}</div> : null}
          <div className="af-stage">{preview}</div>
          <div className="af-under">
            <BuildRail job={selectedJob} building={building} />
            <div className="af-caption">
              <p>{caption}</p>
              {selectedJob ? (
                <div className="af-caption-actions">
                  <button className="af-button" disabled={!previewUrl} onClick={() => window.open(liveSrc || previewUrl, "_blank", "noopener,noreferrer")} type="button">
                    <ExternalLink aria-hidden="true" size={14} /> Open
                  </button>
                  <button className="af-button" onClick={() => { setReloadKey(value => value + 1); void refreshJob(); }} type="button">
                    <RefreshCw aria-hidden="true" size={14} /> Refresh
                  </button>
                  {verified && ["notes", "checklist"].includes(selectedJob.spec?.template) ? (
                    <button className="af-button" disabled={Boolean(busyAction)} onClick={() => void testJob()} type="button">
                      {busyAction === "test" ? <LoaderCircle className="is-spinning" size={14} /> : <ShieldCheck size={14} />} Test app
                    </button>
                  ) : null}
                  <button className="af-button" disabled={!previewUrl} onClick={() => onRequestAction?.("app-factory:open-preview", { jobId: selectedJob.jobId, root: workspaceRoot })} type="button">
                    <Play aria-hidden="true" size={14} /> Open in Preview
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </main>

        {/* Only shown in a narrow window (CSS container query): Brief and Build share the space under the app. */}
        <div className="af-tabs" role="tablist" aria-label="App Factory sections">
          {[["brief", selectedJob ? "Apps" : "Brief"], ["build", "Build"]].map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={compactPane === id} className={compactPane === id ? "is-on" : ""} onClick={() => setCompactPane(id)}>{label}</button>
          ))}
        </div>

        <aside className="af-brief" aria-label={selectedJob ? "Your apps" : "Describe the app"}>
          {selectedJob ? (
            <section className="af-card af-jobcard" data-tone={tone}>
              <span className="af-eyebrow">{selectedJob.spec?.target === "desktop" ? "NATIVE DESKTOP DRAFT" : "NEYVIA LOCAL DRAFT"}</span>
              <h2>{selectedJob.spec?.name}</h2>
              <p>{selectedJob.spec?.brief}</p>
              <div className="af-progress" aria-label={`${progress.percent}% built`}>
                <i><b style={{ width: `${progress.percent}%` }} /></i>
                <span>{progress.completed} of {progress.total} stages · {progress.percent}%</span>
              </div>
            </section>
          ) : (
            <form className="af-form" onSubmit={createJob}>
              <label>
                App name
                <input autoComplete="off" maxLength={80} onChange={event => setForm(current => ({ ...current, name: event.target.value }))} placeholder="Pocket Field Notes" required value={form.name} />
              </label>
              <label>
                What should it help someone do?
                <textarea maxLength={900} minLength={12} onChange={event => setForm(current => ({ ...current, brief: event.target.value }))}
                  placeholder="Capture field observations, find them quickly, and export a portable record." required rows={4} value={form.brief} />
              </label>
              <label>
                Made for
                <select onChange={event => { const value = event.target.value; setForm(current => ({ ...current, target: value })); setFrameChoice(null); }} value={form.target}>
                  <option value="desktop">Native desktop (Windows)</option>
                  <option value="neyvia">Neyvia local app (browser)</option>
                  <option value="ios-studio">iPhone or iPad (iOS Studio)</option>
                </select>
              </label>
              <div className="af-pair">
                <label>
                  First flow
                  <select disabled={Boolean(selectedHandoff)} onChange={event => setForm(current => ({ ...current, template: event.target.value }))} value={form.template}>
                    {selectedHandoff ? <option value="capability">Verified guided workflow</option> : null}
                    <option value="auto">Choose from brief</option>
                    <option value="checklist">Saved checklist</option>
                    <option value="notes">Saved notes</option>
                  </select>
                </label>
                <label>
                  <span>Folder <small>(optional)</small></span>
                  <input autoComplete="off" onChange={event => setForm(current => ({ ...current, directory: event.target.value }))} placeholder="apps/app-name" value={form.directory} />
                </label>
              </div>
              <div className="af-tones" role="radiogroup" aria-labelledby="af-tone-label">
                <span id="af-tone-label" className="af-tones-label">Visual tone</span>
                {[["midnight", "Midnight"], ["paper", "Paper"], ["warm", "Warm"]].map(([id, label]) => (
                  <label key={id} className={form.theme === id ? "is-on" : ""} data-tone-swatch={id}>
                    <input type="radio" name="af-tone" value={id} checked={form.theme === id} onChange={() => setForm(current => ({ ...current, theme: id }))} />
                    <i aria-hidden="true" />{label}
                  </label>
                ))}
              </div>
              {form.target !== "ios-studio" ? (
                <div className="af-note" data-ready={selectedTarget?.available !== false}>
                  <Code2 aria-hidden="true" size={15} />
                  {/* Toolchain details only matter when something is missing. */}
                  <span>{selectedTarget?.available === false ? selectedTarget.readiness : form.target === "desktop" ? "Ready to build a Windows app on this PC." : "Local preview is ready."}</span>
                </div>
              ) : null}
              {selectedHandoff ? (
                <label className="af-confirm">
                  <input checked={handoffReviewConfirmed} onChange={event => setHandoffReviewConfirmed(event.target.checked)} type="checkbox" />
                  <span>I reviewed the sealed workflow, digest-bound proof, unchanged authority, rollback path, and inactive local-draft boundary.</span>
                </label>
              ) : null}
              {form.target === "ios-studio" ? (
                <button className="af-primary" onClick={() => onSetSurface?.("ios-studio")} type="button">
                  <Smartphone size={16} /> Continue in iOS Studio
                </button>
              ) : (
                <button className="af-primary" disabled={busyAction === "create" || (Boolean(selectedHandoff) && !handoffReviewConfirmed)} type="submit">
                  {busyAction === "create" ? <LoaderCircle className="is-spinning" size={16} /> : <Rocket size={16} />}
                  {busyAction === "create" ? "Building pipeline…" : selectedHandoff ? "Shape verified capability" : "Make the app"}
                </button>
              )}
            </form>
          )}

          {eligibleHandoffs.length || selectedHandoff ? <section className="af-card af-capabilities" aria-label="Proven capability sources">
            <header>
              <div><span className="af-eyebrow">PROVEN CAPABILITIES</span><strong>Shape tested work into an app</strong></div>
              <em>{eligibleHandoffs.length} ready</em>
            </header>
            {eligibleHandoffs.length ? (
              <div className="af-list">
                {eligibleHandoffs.map(handoff => (
                  <button className={handoff.handoffId === selectedHandoffId ? "is-on" : ""} key={handoff.handoffId} onClick={() => { newApp(); selectHandoff(handoff); }} type="button">
                    <span>
                      <strong>{handoff.label || handoff.skillId}</strong>
                      <small>{Number(handoff.evidenceSummary?.qualifyingRunCount || 0)} qualifying runs · {handoff.evidenceSummary?.authorityComparison?.status || "reviewed"} authority</small>
                    </span>
                    <ArrowRight aria-hidden="true" size={14} />
                  </button>
                ))}
              </div>
            ) : (
              <p>No inactive skill package is eligible yet. A sealed comparison, approval, and materialization must all pass first.</p>
            )}
            {selectedHandoff ? (
              <div className="af-selection">
                <ShieldCheck aria-hidden="true" size={15} />
                <span><strong>Exact source selected</strong><small>{compactFactoryHash(selectedHandoff.candidateDigest)}</small></span>
                <button className="af-button" onClick={clearHandoff} type="button">Use a blank starter</button>
                <p>{selectedHandoff.rule}</p>
              </div>
            ) : null}
          </section> : null}

          <section className="af-card af-history" aria-label="Recent factory jobs">
            <header>
              <span className="af-eyebrow">YOUR APPS</span>
              <button aria-label="Refresh App Factory jobs" className="af-iconbtn" disabled={loading || busyAction === "refresh"} onClick={() => void refreshCatalog()} type="button">
                <RefreshCw aria-hidden="true" size={14} />
              </button>
            </header>
            {loading ? <p role="status" className="af-loading"><span className="af-shimmer" />Reading factory receipts…</p> : null}
            {!loading && catalog.jobs.length === 0 ? <p>No apps made in this workspace yet. The first one appears here.</p> : null}
            <div className="af-list">
              {catalog.jobs.map(job => {
                const jobProgress = appFactoryProgress(job);
                return (
                  <button className={job.jobId === selectedJobId ? "is-on" : ""} data-job-tone={appFactoryJobTone(job)} key={job.jobId} onClick={() => { selectJob(job); setFrameChoice(null); }} type="button">
                    <span>
                      <strong>{job.spec?.name || "Untitled app"}</strong>
                      <small>{job.capabilityHandoff ? "verified capability" : job.spec?.target === "desktop" ? "desktop" : "local app"}</small>
                    </span>
                    <em>{jobProgress.percent}%</em>
                  </button>
                );
              })}
            </div>
          </section>
          <p className="af-workspace" title={displayWorkspaceRoot}>Workspace · <strong>{workspaceName}</strong></p>
        </aside>

        <aside className="af-inspector" aria-label="Build receipts">
          {selectedJob ? (
            <>
              {selectedJobHandoff ? (
                <section className="af-card af-lineage" aria-label="Verified capability source">
                  <header>
                    <ShieldCheck aria-hidden="true" size={16} />
                    <span><small className="af-eyebrow">VERIFIED CAPABILITY SOURCE</small><strong>{selectedJobHandoff.skillId}</strong></span>
                  </header>
                  <em>Skill inactive · app local draft</em>
                  <dl>
                    <dt>Handoff</dt><dd><code>{compactFactoryHash(selectedJobHandoff.handoffDigest)}</code></dd>
                    <dt>Candidate</dt><dd><code>{compactFactoryHash(selectedJobHandoff.candidateDigest)}</code></dd>
                    <dt>Evidence</dt><dd>{Number(selectedJobHandoff.evidenceSummary?.qualifyingRunCount || selectedJobHandoffReview?.evidenceSummary?.qualifyingRunCount || 0)} qualifying runs</dd>
                    <dt>Authority</dt><dd>{selectedJobHandoff.evidenceSummary?.authorityComparison?.status || selectedJobHandoffReview?.evidenceSummary?.authorityComparison?.status || "reviewed"}</dd>
                  </dl>
                  <p>The exact sealed package is inside this project. The runner guides a human through its explicit steps and seals local proof receipts. Typed outcomes return only when the operator asks; private run text is checked transiently and is not kept in the learning ledger. The app does not invoke an agent, publish itself, or activate the skill.</p>
                </section>
              ) : null}
              <section className="af-receipts" aria-label="App Factory receipts">
                {selectedJobHandoff ? <Receipt detail="Exact package hashes, qualifying comparisons, authority, and app binding are preserved." icon={ShieldCheck} label="Capability lineage" tone="ready" value={compactFactoryHash(selectedJobHandoff.appBindingDigest)} /> : null}
                <Receipt detail={selectedJob.verification?.summary || "Checks have not run."} icon={ShieldCheck} label="Source/package checks" tone={verified ? "ready" : "neutral"} value={selectedJob.verification?.state || "pending"} />
                <Receipt
                  detail={selectedJob.verification?.runtimeProof?.runId
                    ? `Saved journey ${selectedJob.verification.runtimeProof.runId.slice(0, 12)} · ${selectedJob.verification.runtimeProof.situationStatus} · source ${compactFactoryHash(selectedJob.verification.runtimeProof.sourceSha256)}`
                    : "Run Test app to check a real action and reload persistence."}
                  icon={Play} label="App behavior"
                  tone={selectedJob.verification?.runtimeVerified ? "ready" : selectedJob.verification?.runtimeProof ? "danger" : "neutral"}
                  value={selectedJob.verification?.runtimeVerified ? "Journey passed" : selectedJob.verification?.runtimeProof ? "Journey failed" : "Not tested"} />
                <Receipt detail={`${formatBytes(packageReceipt.bytes)} · deterministic .nyapp`} icon={PackageCheck} label="Source package" tone={packageReceipt.sha256 ? "ready" : "neutral"} value={compactFactoryHash(packageReceipt.sha256)} />
                <Receipt
                  detail={nativeBuild.error || (nativeBuild.artifactPath ? `${formatBytes(nativeBuild.bytes)} · ${compactFactoryHash(nativeBuild.sha256)}` : "Compile when the local draft is ready.")}
                  icon={Hammer} label="Native executable"
                  tone={nativeBuild.state === "ready" ? "ready" : nativeBuild.state === "failed" ? "danger" : nativeBusy ? "working" : "neutral"}
                  value={nativeBuild.state?.replaceAll("_", " ") || "not started"} />
                <Receipt
                  detail={installation.active?.sha256 ? `Per-user Windows install · ${compactFactoryHash(installation.active.sha256)} · ${installation.shortcutPath || "shortcut unavailable"}` : "Install the exact compiled, journey-tested build for this user."}
                  icon={AppWindow} label="Installed app"
                  tone={installation.state === "installed" ? "ready" : installation.state === "broken" ? "danger" : "neutral"}
                  value={installation.state?.replaceAll("_", " ") || "not installed"} />
                <Receipt detail="Signing, publisher trust, OCI evidence, and operator activation stay separate." icon={Box} label="Marketplace" value={selectedJob.registration?.state || "draft"} />
              </section>
              <section className="af-actions" aria-label="Next steps">
                {["failed", "needs_attention"].includes(selectedJob.status) ? (
                  <button className="af-button" disabled={busyAction === "resume"} onClick={() => void resumeJob()} type="button"><RefreshCw size={14} /> Resume pipeline</button>
                ) : null}
                {selectedJob.spec?.target === "desktop" ? (
                  <button className="af-button" disabled={!canBuildNative || busyAction === "native"} onClick={() => void buildNative()} type="button">
                    {nativeBusy ? <LoaderCircle className="is-spinning" size={14} /> : <Hammer size={14} />}
                    {nativeBuild.state === "ready" ? "Native build compiled" : nativeBusy ? "Compiling…" : "Build native app"}
                  </button>
                ) : null}
                {canInstallNative ? (
                  <button className="af-button" disabled={Boolean(busyAction)} onClick={() => void installNative()} type="button"><AppWindow size={14} /> {installation.state === "update_available" ? "Update installed app" : "Install tested app"}</button>
                ) : null}
                {installation.rollbackAvailable ? (
                  <button className="af-button" disabled={Boolean(busyAction)} onClick={() => void rollbackNative()} type="button"><RefreshCw size={14} /> Roll back installed app</button>
                ) : null}
                <button className="af-button is-accent" onClick={() => onRequestAction?.("app-factory:continue-agent", { jobId: selectedJob.jobId, projectRoot: selectedJob.projectRoot, previewUrl: selectedJob.previewUrl, prompt: selectedJob.agentHandoff?.prompt })} type="button">
                  <Bot size={14} /> Continue with Agent
                </button>
                <button className="af-button" onClick={() => onOpenPanel?.("marketplace")} type="button"><Box size={14} /> Marketplace gates</button>
              </section>
              <footer className="af-foot">
                <span title={selectedJob.projectRoot}><FolderTree aria-hidden="true" size={13} /> {selectedJob.projectRoot}</span>
                <span>Created {readableDate(selectedJob.createdAt)} · <code>{selectedJob.jobId}</code></span>
                <span>Local draft ≠ published app</span>
              </footer>
            </>
          ) : (
            <section className="af-card af-howto">
              <span className="af-eyebrow">HOW IT GOES</span>
              <ol>
                <li><strong>Describe it.</strong> A name and one useful task. The sketch takes shape as you type.</li>
                <li><strong>Make it.</strong> The pipeline scaffolds, assembles and checks the app; each stage lights up under the frame.</li>
                <li><strong>Use it.</strong> The real app replaces the sketch, running in its frame. Test it, then refine it with your agent.</li>
              </ol>
              <div className="af-mobile-route">
                <Smartphone aria-hidden="true" size={16} />
                <span><strong>iPhone or iPad?</strong> iOS Studio keeps the Apple-aware build route.</span>
                <button className="af-button" onClick={() => onSetSurface?.("ios-studio")} type="button">Open iOS Studio</button>
              </div>
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
