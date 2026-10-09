import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Download, ExternalLink, Pause, Play, RotateCcw, TriangleAlert } from "lucide-react";

import "./nxOnboarding.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { Button, Icon, Spinner, useFocusTrap } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { os, useOs } from "./nxOsStore.js";
import { NxTour } from "./NxTour.jsx";
import { usePackStatus } from "./NxOnboardingPacks.jsx";
import { DownloadsStep, useComponents } from "./NxOnboardingDownloads.jsx";
import { ConnectionsStep } from "./NxOnboardingConnections.jsx";
import { STEPS, STEP_LABELS, UNLOCKS, componentGroups, componentView, essentialsView, interestsFor, recommend, stepFor, uniqueChapters } from "./nxOnboardingModel.js";

// First run and "Setup and tour": welcome, what is unique to Neyvia (real screens, each tied to the
// download that unlocks it), the downloads (Core, Claude Code mod, Codex skills, optional packs),
// connections, done. Every choice is saved through onboarding_save_command, the same state
// neyvia.onboarding.* reads.

function useSnapshot(open) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    let live = true;
    callNx("onboarding_state_command").then(result => { if (live) { setData(result); setError(""); } })
      .catch(failure => { if (live) setError(failure?.message || "Setup could not load."); });
    return () => { live = false; };
  }, [open]);
  return { data, error };
}

/** On a fresh install, open setup once. */
function useFirstRun() {
  useEffect(() => {
    let live = true;
    callNx("onboarding_state_command").then(result => {
      if (live && result?.state?.firstRun && !result.state.dismissed) os.openOnboarding("welcome");
    }).catch(() => { /* an older PC service has no setup; nothing to show */ });
    return () => { live = false; };
  }, []);
}

function WelcomeStep({ basePack, onStatus, firstRun }) {
  const view = essentialsView(basePack);
  const started = useRef(false);
  const act = useCallback(async command => {
    try { onStatus(await callNx(command)); } catch (failure) { onStatus({ ...basePack, state: "failed", error: failure?.message || "The download could not start." }); }
  }, [basePack, onStatus]);

  // First launch starts the download on its own; later visits only show it.
  useEffect(() => {
    if (started.current || !basePack) return;
    started.current = true;
    if (firstRun && basePack.state === "idle") void act("onboarding_base_pack_start_command");
  }, [basePack, firstRun, act]);

  useEffect(() => {
    if (!view.busy) return undefined;
    const timer = setInterval(() => { callNx("onboarding_base_pack_status_command").then(onStatus).catch(() => {}); }, 600);
    return () => clearInterval(timer);
  }, [view.busy, onStatus]);

  return (
    <div className="nx-onb-step">
      <div className="nx-onb-hero">
        <ProviderMark id="neyvia" size={44} />
        <h2 id="nx-onb-title">Welcome to Neyvia</h2>
        <p>One place to work with all your AI agents, see your apps, and keep proof of what was done. Setup takes about three minutes and every step can be skipped.</p>
      </div>
      <ol className="nx-onb-agenda" aria-label="What happens next">
        <li><b>See what is different</b><small>A one minute tour on real screens</small></li>
        <li><b>Choose your downloads</b><small>Core is on, the rest is optional</small></li>
        <li><b>Connect your agents</b><small>Claude Code, Codex and more</small></li>
      </ol>
      <div className={`nx-onb-card is-download is-${view.state}`}>
        <div className="nx-onb-card-head">
          <span className="nx-onb-card-icon">{view.state === "done" ? <Icon as={Check} size={18} /> : view.state === "failed" ? <Icon as={TriangleAlert} size={18} /> : view.busy ? <Spinner size={16} /> : <Icon as={Download} size={18} />}</span>
          <div>
            <strong>{view.headline}</strong>
            <small>{view.detail}</small>
          </div>
          <span className="nx-head-spacer" />
          {view.busy ? <Button variant="ghost" size="sm" icon={Pause} onClick={() => void act("onboarding_base_pack_pause_command")}>Pause</Button> : null}
          {view.state === "paused" || view.state === "idle" ? <Button variant="outline" size="sm" icon={Play} onClick={() => void act("onboarding_base_pack_start_command")}>{view.state === "idle" ? "Start" : "Resume"}</Button> : null}
          {view.state === "failed" ? <Button variant="outline" size="sm" icon={RotateCcw} onClick={() => void act("onboarding_base_pack_start_command")}>Try again</Button> : null}
        </div>
        <div className="nx-onb-meter" role="progressbar" aria-label="Essentials download" aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.percent}>
          <i style={{ width: `${view.percent}%` }} />
        </div>
        <small className="nx-onb-fine">
          {basePack?.files?.total ? `${basePack.files.done} of ${basePack.files.total} files` : "The app, its look and the helpers it needs"}
          {basePack?.channel === "test" ? " · test pack" : ""}
          {view.state !== "done" ? " · you can keep going while this finishes" : ""}
        </small>
      </div>
    </div>
  );
}

/** Under each tour caption: what unlocks the feature, and a way to get it. */
function UnlockNote({ chapter, rows, onGo }) {
  const unlock = UNLOCKS[chapter.unlockedBy];
  if (!unlock) return null;
  const groups = componentGroups(rows);
  const row = chapter.unlockedBy === "claude-mod" ? groups.claudeMod : chapter.unlockedBy === "codex-skills" ? groups.codexSkills : null;
  const on = row ? componentView(row).installed : false;
  return (
    <p className="nx-tour-unlock" data-unlock={chapter.unlockedBy}>
      <span className={`nx-onb-tag${on ? " is-on" : ""}`}>{on ? `${unlock.label} · on` : unlock.label}</span>
      {unlock.step && !on ? <button type="button" className="nx-link" onClick={() => onGo(unlock.step)}>{chapter.unlockedBy === "connections" ? "Connect an agent" : "Turn it on"}</button> : null}
    </p>
  );
}

function UniqueStep({ chapters, rows, onChapter, onGo }) {
  return (
    <div className="nx-onb-step is-wide">
      <div className="nx-onb-step-head">
        <h2 id="nx-onb-title">What makes Neyvia different</h2>
        <p>{["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"][chapters.length] || chapters.length} things a plain chat window does not do. Each one says what unlocks it.</p>
      </div>
      <NxTour chapters={chapters} onChapter={onChapter} extra={chapter => <UnlockNote chapter={chapter} rows={rows} onGo={onGo} />} />
    </div>
  );
}

function DoneStep({ rows, basePack, packStatuses, runtimes, onGo }) {
  const groups = componentGroups(rows);
  const core = essentialsView(basePack);
  const found = (runtimes?.runtimes || []).filter(row => row.found);
  const installedPacks = Object.values(packStatuses || {}).filter(row => row?.state === "installed").length;
  const mod = (row, label) => {
    const view = row ? componentView(row) : null;
    return { label, ok: Boolean(view?.installed), text: view?.installed ? "On" : view?.state === "unavailable" ? "Not available here" : "Off" };
  };
  const lines = [
    { label: "Core", ok: core.state === "done", text: core.state === "done" ? "Installed" : core.headline, go: "welcome" },
    { ...mod(groups.claudeMod, "Claude Code mod"), go: "downloads" },
    { ...mod(groups.codexSkills, "Codex skills"), go: "downloads" },
    { label: "Optional packs", ok: installedPacks > 0, text: installedPacks ? `${installedPacks} installed` : "None", go: "downloads" },
    { label: "Agents found", ok: found.length > 0, text: found.length ? found.map(row => row.label).join(", ") : "Neyvia's own agent", go: "connections" },
  ];
  return (
    <div className="nx-onb-step">
      <div className="nx-onb-step-head">
        <h2 id="nx-onb-title">You're set</h2>
        <p>Here is where things stand. Everything can be changed later from Setup in the sidebar.</p>
      </div>
      <ul className="nx-onb-summary" aria-label="Setup summary">
        {lines.map(line => (
          <li key={line.label} className={line.ok ? "is-ok" : ""}>
            <span className="nx-onb-check">{line.ok ? <Icon as={Check} size={13} /> : null}</span>
            <b>{line.label}</b><span>{line.text}</span>
            <button type="button" className="nx-link" onClick={() => onGo(line.go)}>Change</button>
          </li>
        ))}
      </ul>
      <div className="nx-onb-first">
        <h3 className="nx-onb-sub">Try this first</h3>
        <ul>
          <li>Press <kbd>Ctrl</kbd> <kbd>Space</kbd> to find any app, chat or action.</li>
          <li>Start a chat and ask for two or three things at once. Watch the checklist.</li>
          <li>Open LAYA from Apps and look at an app the way a model does.</li>
        </ul>
        <p className="nx-onb-fine"><Icon as={ExternalLink} size={11} /> The tour of what makes Neyvia different lives under Help in the sidebar.</p>
      </div>
    </div>
  );
}

export function NxOnboarding() {
  useFirstRun();
  const request = useOs(state => state.onboarding);
  const open = Boolean(request);
  const tourOnly = request?.only === "tour" || request?.only === "unique";
  const { data, error } = useSnapshot(open ? request.at : 0); // reloads each time setup opens
  const [step, setStep] = useState("welcome");
  const [picks, setPicks] = useState(null);
  const [basePack, setBasePack] = useState(null);
  const [runtimes, setRuntimes] = useState(null);
  const [runtimeError, setRuntimeError] = useState("");
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [wantParts, setWantParts] = useState(false);
  const lastChapter = useRef("");
  const dialog = useRef(null);
  const packState = usePackStatus(open && !tourOnly && wantParts);
  const components = useComponents(open && wantParts);

  useEffect(() => { if (request) { setStep(stepFor(request.step)); setWantParts(false); } }, [request]);
  // The PC is asked about downloads only once the person gets near them (or opens the tour, which shows what is on).
  useEffect(() => { if (open && (step === "unique" || step === "downloads" || step === "done" || tourOnly)) setWantParts(true); }, [open, step, tourOnly]);
  useEffect(() => {
    if (!data) return;
    const saved = data.state;
    setPicks({ interests: saved.interests, tier: saved.tier, apps: saved.apps, packs: saved.packs, runtime: saved.runtime });
    setBasePack(data.basePack);
  }, [data]);
  useEffect(() => { if (open) dialog.current?.focus(); }, [open, step]);
  useFocusTrap(dialog, open);

  const check = useCallback(async () => {
    setChecking(true);
    try { setRuntimes(await callNx("onboarding_runtimes_command")); setRuntimeError(""); } catch (failure) { setRuntimeError(failure?.message || "Could not look for agent apps."); }
    setChecking(false);
  }, []);
  useEffect(() => { if (open && !tourOnly && (step === "connections" || step === "done") && !runtimes) void check(); }, [open, tourOnly, step, runtimes, check]);

  const save = useCallback(async patch => {
    try { return await callNx("onboarding_save_command", patch); } catch (failure) {
      os.notify({ level: "warning", message: `Setup wasn't saved: ${failure?.message || "the PC didn't answer"}` });
      return null;
    }
  }, []);

  const close = useCallback(async ({ finished = false } = {}) => {
    if (saving) return;
    setSaving(true);
    const tour = { seen: finished || Boolean(lastChapter.current), lastChapter: lastChapter.current };
    if (tourOnly) await save({ tour });
    else if (picks) await save({ ...picks, tour, ...(finished ? { completed: true } : { dismissed: true }) });
    setSaving(false);
    os.closeOnboarding();
    if (finished && !tourOnly) os.notify({ level: "success", message: "You're all set. Setup is in the sidebar whenever you want it." });
  }, [saving, tourOnly, picks, save]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = event => { if (event.key === "Escape") { event.stopPropagation(); void close(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, close]);

  if (!open) return null;
  const everything = data && picks ? recommend(data.catalog, interestsFor(data.catalog, picks)).chapters : [];
  const chapters = request?.only === "tour" ? everything : uniqueChapters(data?.catalog?.tutorial?.chapters);
  const at = STEPS.indexOf(step);
  const goTo = id => setStep(stepFor(id));
  // From the tour inside Help, "Turn it on" leaves the tour and opens that step of setup.
  const jump = id => { if (tourOnly) os.openOnboarding(stepFor(id)); else goTo(id); };
  const next = async () => {
    // Move on at once; the save finishes in the background and warns if it fails.
    setStep(STEPS[Math.min(STEPS.length - 1, at + 1)]);
    if (picks && step !== "welcome") await save(picks);
  };
  const onChapter = id => { lastChapter.current = id; };

  return (
    <div className="nx-onb-scrim" role="presentation">
      <div className={`nx-onb${tourOnly ? " is-tour-only" : ""}${!tourOnly && step === "unique" ? " is-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="nx-onb-title" ref={dialog} tabIndex={-1}>
        {tourOnly ? null : (
          <nav className="nx-onb-rail" aria-label="Setup steps">
            <div className="nx-onb-brand"><ProviderMark id="neyvia" size={18} /> <span>Setup</span></div>
            {STEPS.map((id, index) => (
              <button key={id} type="button" className={`nx-onb-rail-step${id === step ? " is-on" : ""}${index < at ? " is-done" : ""}`}
                aria-current={id === step ? "step" : undefined} onClick={() => setStep(id)}>
                <span className="nx-onb-rail-dot">{index < at ? <Icon as={Check} size={11} /> : index + 1}</span>{STEP_LABELS[id]}
              </button>
            ))}
          </nav>
        )}
        <div className="nx-onb-body">
          {error ? <div className="nx-onb-step"><p className="nx-onb-error"><Icon as={TriangleAlert} size={14} /> {error}</p></div> : null}
          {!data && !error ? <div className="nx-onb-loading"><Spinner size={16} /> Opening setup…</div> : null}
          {data && picks ? (
            <div className="nx-onb-scroll nx-scroll" key={tourOnly ? "tour" : step}>
              {tourOnly ? (
                <div className="nx-onb-step">
                  <h2 id="nx-onb-title" className="nx-visually-hidden">{request?.only === "unique" ? "What makes Neyvia different" : "Neyvia tour"}</h2>
                  <NxTour chapters={chapters} onChapter={onChapter} onDone={() => void close({ finished: true })}
                    extra={chapter => <UnlockNote chapter={chapter} rows={components.rows} onGo={jump} />} />
                </div>
              ) : step === "welcome" ? (
                <WelcomeStep basePack={basePack} onStatus={setBasePack} firstRun={data.state.firstRun} />
              ) : step === "unique" ? (
                <UniqueStep chapters={chapters} rows={components.rows} onChapter={onChapter} onGo={goTo} />
              ) : step === "downloads" ? (
                <DownloadsStep data={data} picks={picks} setPicks={setPicks} packState={packState} components={components} basePack={basePack} onBasePack={setBasePack} />
              ) : step === "connections" ? (
                <ConnectionsStep result={runtimes} error={runtimeError} checking={checking} onCheck={() => void check()}
                  chosen={picks.runtime} onChoose={id => setPicks({ ...picks, runtime: id })} />
              ) : (
                <DoneStep rows={components.rows} basePack={basePack} packStatuses={packState.statuses} runtimes={runtimes} onGo={goTo} />
              )}
            </div>
          ) : null}
          {tourOnly ? null : (
            <footer className="nx-onb-foot">
              {at > 0 ? <Button variant="ghost" onClick={() => setStep(STEPS[at - 1])}>Back</Button> : <Button variant="ghost" onClick={() => void close()}>Skip setup</Button>}
              <span className="nx-head-spacer" />
              {step === "done" ? (
                <Button variant="primary" onClick={() => void close({ finished: true })} disabled={saving}>Finish</Button>
              ) : (
                <Button variant="primary" onClick={() => void next()} disabled={!data || saving}>Continue</Button>
              )}
            </footer>
          )}
        </div>
      </div>
    </div>
  );
}
