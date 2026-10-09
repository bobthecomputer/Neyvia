import {IosCard, AppleTargets} from "./NxAppleTargets.jsx";
import {CopyPath, JobLine, Missing, Check1} from "./NxMobileBuildParts.jsx";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check, ChevronDown, CircleAlert, Copy, Download, ExternalLink, Hammer, Moon, Plus, RefreshCw,
  RotateCw, Smartphone, Sun, TriangleAlert,
} from "lucide-react";

import "./nxMobileStudio.css";
import "../neyviaAppFactoryStudio.css";
import { AppSketch, SAMPLE } from "../NeyviaAppFactoryCanvas.jsx";
import { Phone, insetsFor, shortPath, useFit } from "./NxPhone.jsx";
export { Phone } from "./NxPhone.jsx";
import { backendBase } from "./nxApi.js";
import { approveUiRequest, callTool, reportAppState } from "./nxBus.js";
import { NxFolderPicker } from "./NxFolderPicker.jsx";
import { Button, Icon, IconButton, Spinner, StatusDot, ago, useTick } from "./nxPrimitives.jsx";
import { getOs, os, useOs } from "./nxOsStore.js";

// Mobile Studio (Studio suite): the app in a real-feeling phone beside the chat,
// iPhone and Android builds, installs. Bot side: neyvia.mobile.* on the same
// state (app:mobile-studio); what Paul changes here is reported back.

const KIND_LABELS = { web: "Web app", capacitor: "Capacitor app", expo: "Expo app", "react-native": "React Native app" };
const BEZEL = 12;

/** Call a neyvia.mobile.* tool; a refused call still returns its answer (missing pieces, approval). */
async function mobile(action, args = {}, approvedRequest = "") {
  try {
    if (action === "create" || action === "build" && args.platform === "android") {
      const procedure = action === "create" ? "create-starter-app" : "build-chosen-platform";
      const inputs = action === "create" ? { ...args, ...(approvedRequest ? { approvedRequest } : {}) } : { ...args, build_target: "build" };
      const parameters = Object.entries(inputs).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ");
      const goal = action === "create"
        ? `mobile.status()["project"]["name"] == ${JSON.stringify(args.name)} and mobile.status()["preview"]["ready"] == true`
        : `mobile.status(project=${JSON.stringify(args.project)})["project"]["root"] == ${JSON.stringify(args.project)}`;
      let receipt;
      try {
        // The procedure verifies this button's outcome; it does not complete
        // unrelated deliverables in the workspace's wider CL task.
        receipt = await callTool("neyvia.cl", { lines: `G: ${goal}\nrun mobile-studio.${procedure}(${parameters})` });
      } catch (failure) {
        if (!failure?.data?.results && !failure?.data?.result) throw failure;
        receipt = failure.data.result ?? failure.data;
      }
      const result = receipt?.result?.data ?? receipt?.result ?? receipt;
      if (result?.ok === false) {
        const failed = result.results?.find(row => row.name === `mobile.${action}` && row.ok === false);
        const output = failed?.result?.data ?? failed?.result;
        let native = output?.toolResult ?? output?.result ?? output;
        // Failed CL actions keep metadata only. Read the exact native receipt for
        // its approval ID or blocked-build details before offering a retry.
        if (output?.receipt_path && output?.receipt_id) {
          const receipt = await callTool("neyvia.files.stat", { path: output.receipt_path, preview: true });
          const file = receipt?.result?.data ?? receipt?.result ?? receipt;
          if (file.previewTruncated || !file.preview) throw new Error("Mobile Studio could not read the complete action receipt.");
          const saved = JSON.parse(file.preview);
          if (saved.tool !== `neyvia.mobile.${action}` || saved.receipt_id !== output.receipt_id || saved.status !== output.status) {
            throw new Error("Mobile Studio received a different action receipt.");
          }
          native = { ok: false, status: saved.status, error: saved.error, ...saved.result };
        }
        if (native?.ok === false) return native;
        throw new Error(result.results?.find(row => row.error)?.error || "Mobile Studio could not verify that action.");
      }
      const state = await mobile("status", action === "create" ? {} : { project: args.project });
      return action === "create"
        ? { ok: true, created: state.project.root, bundleId: state.project.iosBundleId }
        : { ok: true, job: state.jobs?.find(row => row.platform === "android" && row.project === state.project.root && row.kind === "build") };
    }
    if (["preview", "simulate", "build"].includes(action) && args.tier !== "device" && (action !== "build" || ["ios", "ipados", "macos"].includes(args.platform))) {
      const inputs = action === "build" ? {project:args.project} : action === "simulate" ? {project:args.project,...(args.results ? {results:args.results} : {})} : args;
      const parameters = Object.entries(inputs).map(([key,value])=>`${key}=${JSON.stringify(value)}`).join(", ");
      const target = args.platform || "ios";
      const procedure = action === "build" ? `build-verify-preview-${target}` : action === "preview" ? "preview-apple" : args.tier === "instant" ? `preview-frame-${target}` : args.results ? `import-cloud-${target}` : `prepare-cloud-off-${target}`;
      const project = JSON.stringify(args.project);
      const goal = action === "build" ? `mobile.verify(project=${project},platform=${JSON.stringify(target)})["ok"] == true` : `mobile.status(project=${project})["preview"]["ready"] == true`;
      const receipt = await callTool("neyvia.cl", {lines:`G: ${goal}\nrun mobile-studio.${procedure}(${parameters})\ndone()`});
      let result = receipt?.result ?? receipt;
      if (result.data) result = result.data;
      if (!result.ok) throw new Error(result.results?.find(item=>item.error)?.error || "The requested Apple outcome could not be verified.");
      const state = await mobile("status", {project:args.project});
      if (action === "build") return {ok:true,job:state.jobs?.find(row=>row.platform === target)};
      if (action === "simulate" && args.tier === "cloud") return args.results ? state.cloudResult : state.cloudPreparation;
      return {ok:true,...state.preview};
    }
    const receipt = await callTool(`neyvia.mobile.${action}`, args);
    return receipt?.result?.data ?? receipt?.result ?? receipt;
  } catch (error) {
    if (error?.data?.result) return error.data.result;
    throw error;
  }
}

/** The person pressed the button, so their click is the approval; then the call runs. */
async function mobileApproved(action, args) {
  const folder = async () => {
    const receipt = await callTool("neyvia.files.list", { path: args.path, showHidden: true });
    const result = receipt?.result?.data ?? receipt?.result ?? receipt;
    if (result.truncated) throw new Error("Choose a smaller folder so starter creation can be checked safely.");
    return JSON.stringify(result.entries);
  };
  const before = action === "create" ? await folder() : null;
  const first = await mobile(action, args);
  if (first?.status !== "approval_required") return first;
  await approveUiRequest(first.approvalId);
  // The click answered it; the approval notice the backend raised has nothing left to ask.
  const clear = () => { for (const notice of getOs().notices.filter(row => row.approvalId === first.approvalId)) os.dismiss(notice.id); };
  clear();
  setTimeout(clear, 1200); // the notice may still be on its way over the bus
  if (action === "create" && await folder() !== before) {
    throw new Error("The destination changed while approval was pending. Inspect it before creating the app again.");
  }
  return mobile(action, args, action === "create" ? first.approvalId : "");
}

// ------------------------------------------------------------- side panels

function AndroidCard({ status, busy, onBuild, onInstall, askShell, onShell }) {
  const android = status.android || {};
  const jobs = (status.jobs || []).filter(row => row.platform === "android" && row.project === status.project?.root);
  const last = status.builds?.android;
  const online = (android.devices || []).filter(device => device.state === "device");
  const targets = [
    ...online.map(device => ({ value: device.serial, label: `${device.emulator ? "Emulator" : "Phone"} ${device.model || device.serial}` })),
    ...(android.avds || []).filter(() => !online.some(device => device.emulator)).map(avd => ({ value: `avd:${avd}`, label: `Start ${avd.replace(/_/g, " ")}` })),
  ];
  const [target, setTarget] = useState("");
  const chosen = target || targets[0]?.value || "";
  const has = name => !(android.missing || []).some(item => item.id === name);
  const running = jobs.some(job => job.status === "running");
  return (
    <section className="nx-ms-card" aria-label="Android">
      <header><Icon as={Smartphone} size={15} /><strong>Android</strong><span>{android.ready ? "Ready to build" : "Build tools missing"}</span></header>
      <ul className="nx-ms-checks">
        <Check1 ok={has("jdk")} detail={android.javaVersion ? `Java ${android.javaVersion}` : ""}>Java</Check1>
        <Check1 ok={Boolean(android.sdk)} detail={android.sdk ? shortPath(android.sdk) : ""}>Android SDK</Check1>
        <Check1 ok={has("build-tools") && Boolean(android.sdk)} detail={android.buildTools?.at(-1) || ""}>Build tools</Check1>
        <Check1 ok={has("platform") && Boolean(android.sdk)} detail={android.platforms?.at(-1) || ""}>Android platform</Check1>
        <Check1 ok={android.emulatorReady} detail={android.avds?.length ? `${android.avds.length} phone${android.avds.length > 1 ? "s" : ""}` : ""}>Emulator</Check1>
      </ul>
      {(android.notes || []).map(note => <p key={note} className="nx-ms-note"><Icon as={TriangleAlert} size={13} />{note}</p>)}
      <Missing items={android.missing} title={android.missing?.length ? `To build: ${android.totalMissing} of downloads` : ""} />
      <Missing items={android.emulatorMissing} title={android.emulatorMissing?.length ? "To run an emulator" : ""} />
      {!android.ready ? <p className="nx-ms-copy">Neyvia doesn't download these by itself. Android Studio (about 1.3 GB) brings all of them at once. {android.gradleNote}</p> : null}
      <div className="nx-ms-row">
        <Button size="sm" variant={android.ready ? "primary" : "outline"} icon={Hammer} disabled={busy || running} onClick={onBuild}>Build .apk</Button>
      </div>
      {askShell ? (
        <div className="nx-ms-confirm">
          <span>This app has no Android shell yet. Add one with Capacitor (about 25 MB of npm packages), then build?</span>
          <Button size="sm" variant="primary" onClick={() => onShell(true)}>Add and build</Button>
          <Button size="sm" variant="ghost" onClick={() => onShell(false)}>Not now</Button>
        </div>
      ) : null}
      {last?.status === "completed" ? (
        <>
          <div className="nx-ms-artifact"><span>Last .apk</span><CopyPath path={last.artifactPath} /></div>
          <div className="nx-ms-row">
            <select className="nx-ms-select" value={chosen} onChange={event => setTarget(event.target.value)} aria-label="Install on">
              {targets.length ? targets.map(row => <option key={row.value} value={row.value}>{row.label}</option>) : <option value="">No phone or emulator found</option>}
            </select>
            <Button size="sm" variant="outline" disabled={!chosen || busy || running} onClick={() => onInstall(chosen)}>Install</Button>
          </div>
        </>
      ) : null}
      {jobs.slice(0, 2).map(job => <JobLine key={job.id} job={job} />)}
    </section>
  );
}

// ---------------------------------------------------------- empty state

// The iPhone 16 Pro (grant_agent/neyvia_mobile_studio.py DEVICES) for the empty studio's sample.
const SAMPLE_PHONE = { id: "iphone-16-pro", platform: "ios", width: 402, height: 874, radius: 62, cutout: "island", statusBar: 54, home: "indicator",
  safe: { portrait: [62, 0, 34, 0], landscape: [0, 62, 21, 62] } };

function Start({ onOpen, onCreate, busy, error }) {
  const [folder, setFolder] = useState(null);
  const [parent, setParent] = useState("");
  const [name, setName] = useState("");
  // The empty studio is not a form alone: a phone beside it already shows a small app, and the
  // name typed into the form appears on it as you type (a sketch; the real app replaces it).
  const sample = { ...SAMPLE, name: name.trim() || SAMPLE.name, template: "checklist", brief: name.trim() ? "Your starter app, ready to open in the phone and to build for iPhone and Android." : SAMPLE.brief };
  return (
    <div className="nx-ms-start">
      <figure className="nx-ms-start-phone" aria-label="A sample app in the phone">
        <Phone device={SAMPLE_PHONE} orientation="portrait" dark scale={0.56}>
          <AppSketch spec={sample} items={name.trim() ? [] : ["Water the tomatoes", "Repot the basil", "Order seeds"]} narrow />
        </Phone>
        <figcaption>{name.trim() ? "Sketch of your app" : "Sample"}</figcaption>
      </figure>
      <div className="nx-ms-start-card">
        <Icon as={Smartphone} size={22} />
        <strong>Build a phone app</strong>
        <p>Open your app's folder, or start from a small working app. It shows in a phone right here and updates as you edit.</p>
        <p className="nx-ms-what">What this is: your web app (HTML, Capacitor or Expo web) in a phone frame, plus real iPhone and Android builds. It isn't a Swift or Kotlin editor, and there's no iPhone simulator on Windows.</p>
        <div className="nx-ms-start-row">
          <NxFolderPicker value={folder} recent={[]} title="Open your app's folder" hint="A web, Capacitor or Expo project" onChange={next => { setFolder(next); onOpen(next.path); }} />
        </div>
        <div className="nx-ms-or">or</div>
        <form className="nx-ms-start-create" onSubmit={event => { event.preventDefault(); if (parent.trim() && name.trim()) onCreate(parent.trim(), name.trim()); }}>
          <label>App name<input value={name} onChange={event => setName(event.target.value)} placeholder="Pocket Garden" /></label>
          {/* One place to choose where the new app goes; the picker also accepts a typed path. */}
          <div className="nx-ms-save-in"><span>Save it in</span>
            <NxFolderPicker value={parent ? { path: parent } : null} recent={[]} title="Choose where to save it" hint="Its own folder is made inside" onChange={next => setParent(next.path)} />
          </div>
          <Button type="submit" variant="primary" icon={Plus} disabled={busy || !parent.trim() || name.trim().length < 2}>Create starter app</Button>
        </form>
        {error ? <p className="nx-ms-error" role="alert">{error}</p> : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- app

export function NxMobileStudio({ target }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState({ device: "", orientation: "portrait", dark: false, textScale: 1, keyboard: false });
  const [reloadKey, setReloadKey] = useState(0);
  const [app, setApp] = useState(null);
  const [appErrors, setAppErrors] = useState([]);
  const [lastReload, setLastReload] = useState(null);
  const [askShell, setAskShell] = useState(false);
  const frameRef = useRef(null);
  const [stageEl, setStageEl] = useState(null); // a state ref: the stage mounts after the start screen
  const project = status?.project?.root || "";
  const inbox = useOs(state => state.inbox);
  useTick(Boolean(lastReload), 5000);

  const refresh = useCallback(async (projectPath) => {
    try {
      const next = await mobile("status", projectPath ? { project: projectPath } : {});
      if (next?.ok === false && next.error) throw new Error(next.error);
      setStatus(next);
      setView(current => current.device ? current : { device: next.device, orientation: next.orientation, dark: next.dark, textScale: next.textScale, keyboard: next.keyboard });
      setError("");
      return next;
    } catch (failure) {
      const text = String(failure?.message || "");
      // A transport error names an internal URL; say what it means instead.
      setError(/error sending request|failed to fetch|network|connection refused|10061|timed out/i.test(text)
        ? "Neyvia on this PC didn't answer. It may still be starting."
        : text || "Mobile Studio could not read its state.");
      return null;
    }
  }, []);

  useEffect(() => { void refresh(target || undefined); }, [refresh, target]);

  // Commands from the bot side: mobile.preview (phone, rotation, dark, folder) and job updates.
  useEffect(() => {
    const mine = inbox.filter(entry => entry.app === "mobile-studio");
    if (!mine.length) return;
    os.drain("mobile-studio", mine.at(-1).seq);
    const shown = mine.filter(entry => entry.action === "mobile.preview").at(-1)?.payload;
    if (shown) {
      setView(current => ({ ...current, device: shown.device || current.device, orientation: shown.orientation || current.orientation, dark: shown.dark ?? current.dark, textScale: shown.textScale ?? current.textScale, keyboard: shown.keyboard ?? current.keyboard }));
    }
    void refresh(shown?.project || project || undefined);
  }, [inbox, refresh, project]);

  const running = (status?.jobs || []).some(job => job.status === "running");
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) void refresh(project || undefined); }, running ? 2000 : 15000);
    return () => clearInterval(timer);
  }, [refresh, project, running]);

  const devices = status?.devices || [];
  const device = devices.find(row => row.id === view.device) || devices[0];
  const preview = status?.preview;

  const change = patch => {
    setView(current => {
      const next = { ...current, ...patch };
      reportAppState("mobile-studio", { ...next, project });
      return next;
    });
  };

  // The phone helper inside the page talks back: look, errors, reloads.
  useEffect(() => {
    const onMessage = event => {
      if (!frameRef.current || event.source !== frameRef.current.contentWindow || event.data?.source !== "nx-mobile") return;
      const data = event.data;
      if (data.type === "sdk-request") {
        const frame = frameRef.current;
        const routes = { state: "__neyvia/state", commit: "__neyvia/commit", identity: "identity.json" };
        const route = routes[data.operation];
        const base = new URL(frame.src, location.href);
        if (!route || base.origin !== location.origin || !base.pathname.startsWith("/api/ui/mobile-preview/")) return;
        const reply = payload => frame.contentWindow?.postMessage({ source: "nx-studio", type: "sdk-response", id: data.id, ...payload }, "*");
        void fetch(new URL(route, base), data.operation === "commit"
          ? { method: "POST", credentials: "omit", headers: { "Content-Type": "application/json", "X-Neyvia-App": "1" }, body: JSON.stringify(data.body) }
          : { credentials: "omit", cache: "no-store" })
          .then(async response => reply({ status: response.status, value: await response.json() }))
          .catch(error => reply({ status: 502, value: { ok: false, error: error.message } }));
      }
      if (data.type === "sdk-control-result") frameRef.current.__nxSdkControl = data;
      if (data.type === "ready") { setApp(data); setAppErrors([]); }
      if (data.type === "error") setAppErrors(current => [...current.slice(-2), data]);
      if (data.type === "reloaded") setLastReload({ at: Date.now(), what: data.what });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // Rotation changes the safe areas without reloading the app, like a phone.
  useEffect(() => {
    if (!device || !frameRef.current) return;
    frameRef.current.contentWindow?.postMessage({ source: "nx-studio", type: "safe", safe: insetsFor(device, view.orientation) }, "*");
  }, [device, view.orientation]);

  const src = useMemo(() => {
    if (!preview?.url || !device) return "";
    if (preview.mode === "expo") return preview.url;
    return `${backendBase()}${preview.url}?device=${device.id}&orientation=${view.orientation}&dark=${view.dark ? 1 : 0}&textScale=${view.textScale}&keyboard=${view.keyboard ? 1 : 0}&r=${reloadKey}`;
    // Rotation is applied live; the page reloads only for another phone (its user agent), dark mode or a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview?.url, preview?.mode, device?.id, view.dark, view.textScale, view.keyboard, reloadKey]);
  useEffect(() => { setApp(null); }, [src]);

  const landscape = view.orientation === "landscape";
  const outer = device ? (() => {
    const se = device.home === "button";
    const w = (landscape ? device.height : device.width) + (se ? (landscape ? 144 : 28) : BEZEL * 2);
    const h = (landscape ? device.width : device.height) + (se ? (landscape ? 28 : 144) : BEZEL * 2);
    return { width: w, height: h };
  })() : { width: 400, height: 800 };
  const scale = useFit(stageEl, outer);

  const act = async (work, success) => {
    setBusy(true);
    try {
      const result = await work();
      if (result?.ok === false) {
        const missing = result.missing?.length ? ` Missing: ${result.missing.map(item => `${item.label} (${item.size})`).join(", ")}.` : "";
        os.notify({ level: result.status === "blocked" ? "warning" : "error", message: (result.error || "That didn't work.") + missing });
      } else if (success) os.notify({ level: "info", message: success });
      await refresh(project || undefined);
      return result;
    } catch (failure) {
      os.notify({ level: "error", message: failure?.message || "That didn't work." });
      return null;
    } finally { setBusy(false); }
  };

  const openFolder = async path => {
    const result = await act(() => mobile("preview", { project: path }));
    if (result?.ok !== false) { setApp(null); await refresh(path); }
  };
  const create = async (parent, name) => {
    const result = await act(() => mobileApproved("create", { path: parent, name }), `Created ${name}`);
    if (result?.created) await refresh(result.created);
  };

  if (!status && !error) return <div className="nx-stage-loading"><Spinner size={16} /></div>;
  if (!status) return <div className="nx-pane-honest"><Icon as={TriangleAlert} size={22} /><strong>Mobile Studio can't reach the PC</strong><p>{error}</p><Button size="sm" variant="outline" onClick={() => void refresh(target || undefined)}>Try again</Button></div>;
  if (!status.project) return <div className="nx-ms"><Start onOpen={openFolder} onCreate={create} busy={busy} error={error} /></div>;

  const info = status.project;
  const absolute = src && preview?.mode === "static" ? new URL(src, window.location.href).href : src;
  return (
    <div className="nx-ms">
      <div className="nx-ms-main">
        <div className="nx-ms-bar">
          <select className="nx-ms-select" value={device?.id || ""} onChange={event => { change({ device: event.target.value }); setApp(null); }} aria-label="Phone">
            <optgroup label="iPhone">{devices.filter(row => row.platform === "ios").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</optgroup>
            <optgroup label="Android">{devices.filter(row => row.platform === "android").map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</optgroup>
            <optgroup label="Apple previews">{devices.filter(row => !["ios","android"].includes(row.platform)).map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</optgroup>
          </select>
          <IconButton icon={RotateCw} label={landscape ? "Turn upright" : "Turn sideways"} active={landscape} onClick={() => change({ orientation: landscape ? "portrait" : "landscape" })} />
          <IconButton icon={view.dark ? Moon : Sun} label={view.dark ? "Phone in dark mode" : "Phone in light mode"} active={view.dark} onClick={() => change({ dark: !view.dark })} />
          <IconButton icon={RefreshCw} label="Reload the app" onClick={() => { setApp(null); setReloadKey(key => key + 1); }} disabled={!src} />
          <select className="nx-ms-select" aria-label="Text size" value={view.textScale} onChange={e=>change({textScale:Number(e.target.value)})}>
            <option value="1">Text 100%</option><option value="1.25">Text 125%</option><option value="1.5">Text 150%</option><option value="2">Text 200%</option>
          </select>
          <Button size="sm" active={view.keyboard} onClick={()=>change({keyboard:!view.keyboard})}>Keyboard {view.keyboard ? "on" : "off"}</Button>
          <span className="nx-head-spacer" />
          {absolute ? <a className="nx-ms-link" href={absolute} target="_blank" rel="noreferrer"><Icon as={ExternalLink} size={13} />Open in a tab</a> : null}
        </div>
        <div className="nx-ms-stage" ref={setStageEl}>
          {device ? <Phone device={device} orientation={view.orientation} dark={view.dark} keyboard={view.keyboard} src={src} frameRef={frameRef} app={app} scale={scale}
            sandbox={preview?.mode === "expo" ? "allow-scripts allow-same-origin allow-forms allow-modals allow-popups" : "allow-scripts allow-forms allow-modals allow-popups allow-downloads"} /> : null}
          {!src ? (
            <div className="nx-ms-nopreview">
              <p>{preview?.note || "Nothing to show yet."}</p>
              {preview?.canStartExpo ? <Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => mobile("preview", { startExpo: true }), "Starting the Expo preview")}>Start Expo preview</Button> : null}
            </div>
          ) : null}
        </div>
        <div className="nx-ms-caption">
          <span>Browser preview · emulated behaviour</span>
          {device ? <span>{device.name} · {landscape ? `${device.height} × ${device.width}` : `${device.width} × ${device.height}`}</span> : null}
          {preview?.touch && device?.platform !== "macos" ? <span>Touch on</span> : null}
          {src ? <span><StatusDot tone="ok" /> {preview?.hotReload === "on" ? "Live: saves show at once" : preview?.hotReload}{lastReload ? ` · ${lastReload.what === "styles" ? "styles" : "reloaded"} ${ago(lastReload.at)}` : ""}</span> : null}
        </div>
        {appErrors.length ? <div className="nx-ms-apperror" role="status"><Icon as={TriangleAlert} size={13} /><span>{appErrors.at(-1).message}</span>{appErrors.at(-1).where ? <code>{appErrors.at(-1).where}</code> : null}</div> : null}
      </div>
      <aside className="nx-ms-side nx-scroll" aria-label="Build and install">
        <section className="nx-ms-card is-app" aria-label="App">
          <header><strong>{info.name}</strong><span>{KIND_LABELS[info.kind] || info.kind}</span></header>
          <NxFolderPicker value={{ path: info.root, name: info.name }} recent={[]} onChange={next => openFolder(next.path)} />
          {info.webRoot ? <p className="nx-ms-copy">Screens from <code>{shortPath(info.webRoot)}</code></p> : null}
          {info.iosBundleId ? <p className="nx-ms-copy">ID <code>{info.iosBundleId}</code></p> : <p className="nx-ms-copy">Add an app ID (expo.ios.bundleIdentifier in app.json) before building.</p>}
        </section>
        <IosCard status={status} busy={busy}
          onBuild={() => act(() => mobile("build", { platform: "ios", project }), "iPhone build started")}
          onSetup={() => act(() => mobileApproved("setup", { part: "ios-compiler", project }), "Downloading the iPhone compiler")} />
        <AppleTargets status={status} busy={busy} onAction={(action,args)=>act(()=>mobile(action,args))}/>
        <AndroidCard status={status} busy={busy}
          askShell={askShell}
          onShell={yes => { setAskShell(false); if (yes) void act(() => mobile("build", { platform: "android", project, addShell: true }), "Android build started"); }}
          onBuild={async () => {
            const result = await act(() => mobile("build", { platform: "android", project }), "Android build started");
            setAskShell(Boolean(result?.needsShell));
          }}
          onInstall={value => act(() => mobile("install", value.startsWith("avd:") ? { target: "emulator", avd: value.slice(4), project } : { target: value, project }), "Installing")} />
      </aside>
    </div>
  );
}
