import { useEffect, useMemo, useState } from "react";
import "./iosStudio.css";
import {NeyviaDevicePreview} from './NeyviaDevicePreview.jsx';
import {
  AppleLogo,
  ArrowClockwise,
  ArrowRight,
  CheckCircle,
  CloudArrowUp,
  Code,
  Copy,
  Cpu,
  DeviceMobile,
  FolderOpen,
  HardDrives,
  Play,
  Plus,
  Stop,
  WarningCircle,
  WindowsLogo,
  XCircle,
} from "@phosphor-icons/react";

const PROJECT_ROOT_KEY = "neyvia.iosStudio.projectRoot";

function cleanText(value) {
  return String(value || "").trim();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
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

function resolvedPreviewUrl(rawUrl) {
  if (!rawUrl || typeof window === "undefined") return rawUrl || "";
  try {
    const url = new URL(rawUrl);
    if (["127.0.0.1", "localhost"].includes(url.hostname) && !["127.0.0.1", "localhost"].includes(window.location.hostname)) {
      url.hostname = window.location.hostname;
      url.protocol = window.location.protocol;
    }
    return url.toString();
  } catch {
    return rawUrl;
  }
}

function StatusIcon({ state }) {
  if (state === "ready" || state === "completed") return <CheckCircle aria-hidden="true" size={17} weight="fill" />;
  if (state === "blocked" || state === "failed") return <XCircle aria-hidden="true" size={17} weight="fill" />;
  return <WarningCircle aria-hidden="true" size={17} weight="fill" />;
}

function IosStudioSkeleton() {
  return (
    <div className="ios-studio-skeleton" role="status">
      <span>Reading iOS project</span>
      <div />
      <div />
      <div />
    </div>
  );
}

export function IosStudioSurface({ callBackend, currentProjectLabel, onRequestAction, onSetSurface, workspaceRoot = "" }) {
  const [connectedPreviewUrl, setConnectedPreviewUrl] = useState('');
  const [projectRoot, setProjectRoot] = useState(() => {
    if (typeof window === "undefined") return workspaceRoot;
    return window.localStorage?.getItem(PROJECT_ROOT_KEY) || workspaceRoot;
  });
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [buildMode, setBuildMode] = useState("windows-native");
  const [createForm, setCreateForm] = useState({
    name: "",
    directory: "apps/",
    bundleIdentifier: "",
  });
  const [builderForm, setBuilderForm] = useState({
    label: "Private Mac builder",
    host: "",
    user: "",
    port: "22",
    remoteRoot: "~/NeyviaBuilds",
    identityFile: "",
    appleTeamId: "",
    knownHostsPolicy: "accept-new",
  });
  const [windowsForm, setWindowsForm] = useState({
    engine: "auto",
    distro: "default",
    minimumIos: "16.0",
    identityFile: "",
    certificateFile: "",
    provisioningProfile: "",
  });

  useEffect(() => {
    if (!projectRoot && workspaceRoot) setProjectRoot(workspaceRoot);
  }, [projectRoot, workspaceRoot]);

  useEffect(() => {
    if (typeof window !== "undefined" && projectRoot) {
      window.localStorage?.setItem(PROJECT_ROOT_KEY, projectRoot);
    }
  }, [projectRoot]);

  const refresh = async ({ silent = false } = {}) => {
    const root = cleanText(projectRoot);
    if (!root || typeof callBackend !== "function") return;
    if (!silent) setLoading(true);
    setError("");
    try {
      const next = await callBackend("get_ios_studio_status_command", { root }, { throwOnError: true });
      setStatus(next);
      const builder = next?.builder || {};
      setBuilderForm(current => ({
        ...current,
        label: builder.label || current.label,
        host: builder.host || "",
        user: builder.user || "",
        port: String(builder.port || 22),
        remoteRoot: builder.remoteRoot || "~/NeyviaBuilds",
        identityFile: builder.identityFile || "",
        appleTeamId: builder.appleTeamId || "",
        knownHostsPolicy: builder.knownHostsPolicy || "accept-new",
      }));
      const localConfig = next?.windowsToolchain?.config || {};
      setWindowsForm(current => ({
        ...current,
        engine: localConfig.engine || next?.windowsToolchain?.engine || current.engine,
        distro: localConfig.distro || next?.windowsToolchain?.distro || current.distro,
        minimumIos: localConfig.minimumIos || next?.windowsToolchain?.minimumIos || current.minimumIos,
        identityFile: localConfig.identityFile || "",
        certificateFile: localConfig.certificateFile || "",
        provisioningProfile: localConfig.provisioningProfile || "",
      }));
    } catch (caught) {
      setStatus(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    // projectRoot is the selected app boundary; backend function identity is intentionally ignored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot]);

  const runAction = async (action, task) => {
    setBusyAction(action);
    setError("");
    setNotice("");
    try {
      const result = await task();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return null;
    } finally {
      setBusyAction("");
    }
  };

  const createApp = async event => {
    event.preventDefault();
    const workspace = cleanText(workspaceRoot || projectRoot);
    const result = await runAction("create", () =>
      callBackend(
        "create_ios_app_command",
        {
          root: workspace,
          name: cleanText(createForm.name),
          directory: cleanText(createForm.directory),
          bundleIdentifier: cleanText(createForm.bundleIdentifier),
          installDependencies: true,
        },
        { throwOnError: true },
      ),
    );
    if (result?.projectRoot) {
      setNotice(`${result.appName || "App"} was created with its dependencies installed.`);
      setProjectRoot(result.projectRoot);
      setStatus(result.status || null);
    }
  };

  const saveAndVerifyBuilder = async event => {
    event.preventDefault();
    const result = await runAction("builder", async () => {
      await callBackend(
        "save_ios_builder_command",
        {
          root: projectRoot,
          ...builderForm,
          port: Number(builderForm.port || 22),
        },
        { throwOnError: true },
      );
      return callBackend("probe_ios_builder_command", { root: projectRoot }, { throwOnError: true });
    });
    if (result) {
      const probeReady = Boolean(result?.probe?.ready);
      setNotice(probeReady ? "Mac builder verified. Xcode is ready for private builds." : result?.probe?.summary || "Mac builder needs attention.");
      await refresh({ silent: true });
    }
  };

  const installWindowsCompiler = async () => {
    const result = await runAction("windows-setup", () =>
      callBackend(
        "install_windows_ios_toolchain_command",
        { root: projectRoot, engine: windowsForm.engine, distro: windowsForm.distro },
        { throwOnError: true },
      ),
    );
    if (result) {
      setNotice(
        result.installedEngine === "win32"
          ? "The Windows compatibility toolchain is installed as native Win32 processes."
          : "The WSL2 compatibility toolchain is installed.",
      );
      await refresh({ silent: true });
    }
  };

  const saveWindowsCompiler = async event => {
    event.preventDefault();
    const result = await runAction("windows-save", () =>
      callBackend(
        "save_windows_ios_config_command",
        { root: projectRoot, ...windowsForm },
        { throwOnError: true },
      ),
    );
    if (result) {
      setNotice("Windows compatibility settings saved. Signing secrets were not stored.");
      await refresh({ silent: true });
    }
  };

  const togglePreview = async () => {
    const running = Boolean(status?.preview?.running);
    const command = running ? "stop_ios_preview_command" : "start_ios_preview_command";
    const result = await runAction("preview", () =>
      callBackend(
        command,
        running ? { root: projectRoot } : { root: projectRoot, port: 19006, installDependencies: true },
        { throwOnError: true },
      ),
    );
    if (result) {
      setNotice(running ? "Windows preview stopped." : "Windows preview is starting. The first bundle can take a moment.");
      await refresh({ silent: true });
    }
  };

  const startBuild = async () => {
    const result = await runAction("build", () =>
      callBackend(
        "start_ios_build_command",
        { root: projectRoot, mode: buildMode, timeoutSeconds: 3600 },
        { throwOnError: true },
      ),
    );
    if (result) {
      setNotice(
        result.status === "completed"
          ? `${buildMode === "windows-native" ? "Compatibility package" : "Native Apple build"} completed: ${result.artifactPath}`
          : result.error || "The build failed. Open the receipt for the exact toolchain error.",
      );
      await refresh({ silent: true });
    }
  };

  const selectedMode = useMemo(
    () => status?.buildModes?.find(item => item.id === buildMode) || null,
    [buildMode, status?.buildModes],
  );
  const previewUrl = resolvedPreviewUrl(status?.preview?.url);
  const project = status?.project || {};
  const builder = status?.builder || {};
  const builderProbe = builder.lastProbe || {};
  const windowsToolchain = status?.windowsToolchain || {};
  const history = Array.isArray(status?.history) ? status.history : [];
  const windowsPackageCompleted = history.some(item => item.status === "completed" && item.mode === "windows-native");
  const nativeAppleBuildCompleted = history.some(item => (
    item.status === "completed" &&
    /(?:mac|xcode|remote)/i.test(String(item.mode || ""))
  ));
  const nativeAppleRouteReady = Boolean(builderProbe.ready) || nativeAppleBuildCompleted;

  const copyValue = async value => {
    if (!value || typeof navigator === "undefined" || !navigator.clipboard) return;
    await navigator.clipboard.writeText(value);
    setNotice("Path copied to the clipboard.");
  };

  const openAgent = () => {
    onRequestAction?.("ios-studio:open-agent", {
      projectRoot,
      appName: project.appName,
      bundleIdentifier: project.bundleIdentifier,
      framework: project.framework,
    });
  };

  return (
    <section className="ios-studio" data-ios-studio-surface="true">
      {onSetSurface && <button className="neyvia-surface-back" onClick={() => onSetSurface('app-factory')} type="button">← App Factory</button>}
      <header className="ios-studio-head">
        <div>
          <span className="ios-studio-eyebrow">MOBILE APPS</span>
          <h1>iOS Studio</h1>
          <p>Build your app, try it on a device canvas, and prepare it for iPhone or iPad.</p>
        </div>
      </header>
      <details className="ios-project-setup">
        <summary>Project & build setup <span>Native iOS requires a Mac</span></summary>
        <div className="ios-studio-route" aria-label="iOS build route">
          <div className="ready">
            <WindowsLogo aria-hidden="true" size={20} weight="fill" />
            <span>Windows</span>
            <strong>Author + web preview</strong>
          </div>
          <ArrowRight aria-hidden="true" size={17} weight="bold" />
          <div className={windowsToolchain.ready ? "ready" : "waiting"}>
            <Cpu aria-hidden="true" size={20} weight="regular" />
            <span>{windowsToolchain.nativeProcess ? "Win32 tools" : "Compatibility tools"}</span>
            <strong>{windowsToolchain.ready ? (windowsPackageCompleted ? "Package receipt ready" : "Package tools ready") : "Install tools"}</strong>
          </div>
          <ArrowRight aria-hidden="true" size={17} weight="bold" />
          <div className={nativeAppleRouteReady ? "ready" : "waiting"}>
            <AppleLogo aria-hidden="true" size={20} weight="fill" />
            <span>Native Apple route</span>
            <strong>{nativeAppleRouteReady ? "Mac/Xcode verified" : "Mac/Xcode required"}</strong>
          </div>
        </div>
      <p data-ios-capability-truth="true">The device canvas runs your app’s web version. Native iOS simulation and App Store builds use a connected Mac with Xcode.</p>

      <div className="ios-studio-pathbar">
        <FolderOpen aria-hidden="true" size={18} weight="regular" />
        <label>
          <span>iOS project folder</span>
          <input
            aria-label="iOS project folder"
            onChange={event => setProjectRoot(event.target.value)}
            placeholder="C:\\projects\\pocket-atlas"
            value={projectRoot}
          />
        </label>
        <button className="ios-icon-button" disabled={loading || !projectRoot} onClick={() => void refresh()} title="Refresh project" type="button">
          <ArrowClockwise aria-hidden="true" size={18} weight="bold" />
          <span>Refresh</span>
        </button>
      </div>
      </details>

      {error ? (
        <div className="ios-inline-message error" role="alert">
          <XCircle aria-hidden="true" size={19} weight="fill" />
          <div><strong>iOS Studio could not complete that action.</strong><p>{error}</p></div>
        </div>
      ) : null}
      {notice ? (
        <div className="ios-inline-message notice" role="status">
          <CheckCircle aria-hidden="true" size={19} weight="fill" />
          <p>{notice}</p>
        </div>
      ) : null}

      {loading ? <IosStudioSkeleton /> : null}

      {!project.recognized ? (
        <div className="ios-studio-empty-grid">
          <NeyviaDevicePreview appName={createForm.name || "Your app"} url={connectedPreviewUrl} running={Boolean(connectedPreviewUrl)} onOpenUrl={setConnectedPreviewUrl}/>
          <form className="ios-studio-form" onSubmit={createApp}>
            <div className="ios-form-title"><Plus aria-hidden="true" size={19} weight="bold" /><strong>Create iOS app</strong></div>
            <label>
              <span>App name</span>
              <input
                onChange={event => setCreateForm(current => ({ ...current, name: event.target.value }))}
                placeholder="Pocket Atlas"
                required
                value={createForm.name}
              />
              <small>The name people will see on their device.</small>
            </label>
            <label>
              <span>Project folder</span>
              <input
                onChange={event => setCreateForm(current => ({ ...current, directory: event.target.value }))}
                placeholder="apps/pocket-atlas"
                required
                value={createForm.directory}
              />
              <small>Created inside {currentProjectLabel || "the selected Neyvia workspace"}.</small>
            </label>
            <label>
              <span>Bundle identifier</span>
              <input
                onChange={event => setCreateForm(current => ({ ...current, bundleIdentifier: event.target.value }))}
                placeholder="com.yourname.pocketatlas"
                required
                value={createForm.bundleIdentifier}
              />
              <small>Choose carefully; App Store Connect treats this as the permanent app identity.</small>
            </label>
            <button className="ios-primary-button" disabled={busyAction === "create" || !(workspaceRoot || projectRoot)} type="submit">
              {busyAction === "create" ? "Creating and installing…" : "Create app"}
              <ArrowRight aria-hidden="true" size={17} weight="bold" />
            </button>
          </form>
        </div>
      ) : null}

      {!loading && project.recognized ? (
        <>
          <div className="ios-studio-project-strip">
            <div className="ios-studio-app-mark"><DeviceMobile aria-hidden="true" size={27} weight="regular" /></div>
            <div>
              <span>{project.framework === "expo" ? `Expo ${project.expoVersion || "project"}` : "React Native project"}</span>
              <h2>{project.appName}</h2>
              <code>{project.bundleIdentifier || "Bundle identifier missing"}</code>
            </div>
            <div className="ios-studio-project-actions">
              <button onClick={openAgent} type="button"><Code aria-hidden="true" size={17} weight="regular" />Design with Agent</button>
              <button disabled={busyAction === "preview" || !status?.readiness?.windowsPreview} onClick={() => void togglePreview()} type="button">
                {status?.preview?.running ? <Stop aria-hidden="true" size={17} weight="fill" /> : <Play aria-hidden="true" size={17} weight="fill" />}
                {status?.preview?.running ? "Stop preview" : "Preview web on Windows"}
              </button>
              {status?.preview?.running && previewUrl ? <a href={previewUrl} rel="noreferrer" target="_blank">Open preview</a> : null}
            </div>
          </div>

          <NeyviaDevicePreview appName={project.appName || "Your app"} url={connectedPreviewUrl || previewUrl} running={Boolean(connectedPreviewUrl || status?.preview?.running)} onOpenUrl={setConnectedPreviewUrl} starting={busyAction === "preview"} onStart={status?.readiness?.windowsPreview ? () => void togglePreview() : undefined}/>

          <form className="ios-windows-compiler" onSubmit={saveWindowsCompiler}>
            <div className="ios-windows-compiler-copy">
              <div className="ios-section-heading">
                <div><span>Windows compatibility</span><h2>Prepare a compatibility package</h2></div>
                <WindowsLogo aria-hidden="true" size={27} weight="fill" />
              </div>
              <p>
                Neyvia can run packaging, LLVM, and signing compatibility tools on Windows. This output is not presented as an iOS simulator run or an App Store-native build; native Apple proof requires Mac/Xcode or a physical device.
              </p>
              <div className={`ios-local-proof ${windowsToolchain.ready ? "ready" : "blocked"}`}>
                <StatusIcon state={windowsToolchain.ready ? "ready" : "blocked"} />
                <div>
                  <strong>{windowsToolchain.ready ? "Compatibility toolchain ready" : "Compatibility toolchain not installed"}</strong>
                  <small>{windowsToolchain.ready ? "Windows packaging tools are reported. Native Apple execution remains a separate evidence gate." : windowsToolchain.summary}</small>
                </div>
                {windowsToolchain.tools?.clangVersion ? <code>{windowsToolchain.tools.clangVersion}</code> : null}
              </div>
              <div className={`ios-process-boundary ${windowsToolchain.nativeProcess ? "native" : "fallback"}`}>
                <span>Active process boundary</span>
                <strong>{windowsToolchain.nativeProcess ? "Direct Win32 · no WSL invoked" : windowsToolchain.ready ? `WSL2 compatibility · ${windowsToolchain.distro}` : "Not selected until the compiler is installed"}</strong>
              </div>
            </div>
            <div className="ios-windows-fields">
              <label className="wide">
                <span>Compiler engine</span>
                <select onChange={event => setWindowsForm(current => ({ ...current, engine: event.target.value }))} value={windowsForm.engine}>
                  <option value="auto">Automatic · Direct Windows first</option>
                  <option value="win32">Direct Windows only · No WSL</option>
                  <option value="wsl2">WSL2 compatibility engine</option>
                </select>
                <small>Direct Windows is the recommended path. Automatic uses WSL2 only when Win32 LLVM is not ready.</small>
              </label>
              <label><span>WSL2 fallback distro</span><input disabled={windowsForm.engine === "win32"} onChange={event => setWindowsForm(current => ({ ...current, distro: event.target.value }))} value={windowsForm.distro} /></label>
              <label><span>Minimum iOS</span><input onChange={event => setWindowsForm(current => ({ ...current, minimumIos: event.target.value }))} value={windowsForm.minimumIos} /></label>
              <label className="wide"><span>Private key or P12</span><input onChange={event => setWindowsForm(current => ({ ...current, identityFile: event.target.value }))} placeholder="Optional for a signed device IPA" value={windowsForm.identityFile} /></label>
              <label className="wide"><span>Certificate file</span><input onChange={event => setWindowsForm(current => ({ ...current, certificateFile: event.target.value }))} placeholder="Optional when the identity already contains the certificate" value={windowsForm.certificateFile} /></label>
              <label className="wide"><span>Provisioning profile</span><input onChange={event => setWindowsForm(current => ({ ...current, provisioningProfile: event.target.value }))} placeholder="Optional .mobileprovision path" value={windowsForm.provisioningProfile} /></label>
              <div className="ios-windows-actions wide">
                <button className="ios-secondary-button" disabled={Boolean(busyAction)} type="submit">Save local settings</button>
                <button className="ios-primary-button" disabled={Boolean(busyAction) || windowsToolchain.ready} onClick={() => void installWindowsCompiler()} type="button">
                  <Cpu aria-hidden="true" size={17} weight="bold" />
                  {busyAction === "windows-setup" ? "Installing compatibility tools…" : windowsToolchain.ready ? "Tools installed" : "Install package tools"}
                </button>
              </div>
              <small className="wide">P12 passwords are read only from NEYVIA_IOS_SIGNING_PASSWORD and are never saved in the project.</small>
            </div>
          </form>

          <div className="ios-studio-main-grid">
            <section className="ios-studio-readiness">
              <div className="ios-section-heading">
                <div><span>Build readiness</span><h2>Nothing hidden</h2></div>
                <strong>{status.checks?.filter(item => item.state === "ready").length || 0} ready</strong>
              </div>
              <div className="ios-check-list">
                {(status.checks || []).map(item => (
                  <article className={`ios-check-row state-${item.state}`} key={item.id}>
                    <StatusIcon state={item.state} />
                    <div><strong>{item.label}</strong><p>{item.detail}</p></div>
                    <span>{item.state === "ready" ? "Ready" : item.state === "optional" ? "Optional" : item.state === "missing" ? "Verify" : "Blocked"}</span>
                  </article>
                ))}
              </div>
              {status?.preview?.logPath ? (
                <button className="ios-copy-row" onClick={() => void copyValue(status.preview.logPath)} type="button">
                  <Copy aria-hidden="true" size={16} weight="regular" />
                  <span>Preview log</span>
                  <code>{status.preview.logPath}</code>
                </button>
              ) : null}
            </section>

            <form className="ios-studio-builder" onSubmit={saveAndVerifyBuilder}>
              <div className="ios-section-heading">
              <div><span>Native Apple build route</span><h2>Connect a Mac with Xcode</h2></div>
                <HardDrives aria-hidden="true" size={25} weight="regular" />
              </div>
              <p className="ios-builder-copy">
                Neyvia installs its own small runner over SSH. Source is filtered before transfer and Apple signing material stays in the Mac keychain.
              </p>
              <div className="ios-builder-fields">
                <label className="wide"><span>Builder label</span><input onChange={event => setBuilderForm(current => ({ ...current, label: event.target.value }))} value={builderForm.label} /></label>
                <label><span>Mac host</span><input onChange={event => setBuilderForm(current => ({ ...current, host: event.target.value }))} placeholder="mac-builder.tailnet.ts.net" required value={builderForm.host} /></label>
                <label><span>SSH user</span><input onChange={event => setBuilderForm(current => ({ ...current, user: event.target.value }))} placeholder="builder" required value={builderForm.user} /></label>
                <label><span>SSH port</span><input min="1" max="65535" onChange={event => setBuilderForm(current => ({ ...current, port: event.target.value }))} type="number" value={builderForm.port} /></label>
                <label><span>Remote root</span><input onChange={event => setBuilderForm(current => ({ ...current, remoteRoot: event.target.value }))} value={builderForm.remoteRoot} /></label>
                <label className="wide"><span>SSH identity file</span><input onChange={event => setBuilderForm(current => ({ ...current, identityFile: event.target.value }))} placeholder="Optional; uses ssh-agent when empty" value={builderForm.identityFile} /></label>
                <label className="wide"><span>Apple Team ID</span><input maxLength={10} onChange={event => setBuilderForm(current => ({ ...current, appleTeamId: event.target.value.toUpperCase() }))} placeholder="Required only for signed IPA builds" value={builderForm.appleTeamId} /></label>
              </div>
              <button className="ios-secondary-button" disabled={busyAction === "builder"} type="submit">
                <ArrowClockwise aria-hidden="true" size={17} weight="bold" />
                {busyAction === "builder" ? "Deploying runner and checking Xcode…" : "Save and verify Mac"}
              </button>
              {builder.lastProbeAt ? <small className="ios-last-probe">Last check {readableDate(builder.lastProbeAt)} · {builderProbe.summary}</small> : null}
            </form>
          </div>

          <section className="ios-build-console">
            <div className="ios-section-heading">
              <div><span>Evidence-gated output</span><h2>Build through the correct platform route</h2></div>
              <CloudArrowUp aria-hidden="true" size={25} weight="regular" />
            </div>
            <div className="ios-build-mode-grid">
              {(status.buildModes || []).map(mode => {
                const windowsMode = mode.id === "windows-native";
                return (
                <button
                  aria-pressed={buildMode === mode.id}
                  className={`${buildMode === mode.id ? "selected" : ""} ${mode.ready ? "ready" : "blocked"}`}
                  key={mode.id}
                  onClick={() => setBuildMode(mode.id)}
                  type="button"
                >
                  <span>{windowsMode ? "Windows compatibility package" : mode.label}</span>
                  <p>{windowsMode ? "Packages Windows-side output and records toolchain proof. It is not a native iOS simulator or App Store build." : mode.detail}</p>
                  <strong>{mode.ready ? (windowsMode ? "Ready to package" : "Ready for Mac/Xcode build") : "Resolve blockers"}</strong>
                </button>
                );
              })}
            </div>
            <div className="ios-build-submit">
              <div>
                <span>Selected output</span>
                <strong>{buildMode === "windows-native" ? "Windows compatibility package" : selectedMode?.label || "Choose a build mode"}</strong>
                <p>{buildMode === "windows-native" ? "Compatibility output only; native Apple acceptance still needs Mac/Xcode or device proof." : selectedMode?.detail}</p>
              </div>
              <button className="ios-primary-button" disabled={busyAction === "build" || !selectedMode?.ready} onClick={() => void startBuild()} type="button">
                {busyAction === "build" ? (buildMode === "windows-native" ? "Packaging on Windows…" : "Building with Xcode…") : buildMode === "windows-native" ? "Create compatibility package" : "Start Xcode build"}
                <ArrowRight aria-hidden="true" size={17} weight="bold" />
              </button>
            </div>
          </section>

          <section className="ios-build-history">
            <div className="ios-section-heading">
              <div><span>Receipts</span><h2>Build history</h2></div>
              <strong>{history.length}</strong>
            </div>
            {history.length ? (
              <div className="ios-history-list">
                {history.map(item => (
                  <article className={`ios-history-row state-${item.status}`} key={item.jobId}>
                    <StatusIcon state={item.status} />
                    <div>
                      <strong>{item.appName || project.appName}</strong>
                      <p>{item.mode === "windows-native" ? "Windows compatibility package" : item.mode} · {readableDate(item.updatedAt)}</p>
                      {item.target ? (
                        <code className="ios-history-proof">
                          {item.target} · {item.signatureKind || "unsigned"} · {item.codeSignatureLoadCommand ? "LC_CODE_SIGNATURE" : "signature pending"} · {String(item.artifactSha256 || "").slice(0, 12)}
                        </code>
                      ) : null}
                    </div>
                    <span>{item.status}</span>
                    {item.artifactPath ? <button onClick={() => void copyValue(item.artifactPath)} type="button"><Copy aria-hidden="true" size={15} weight="regular" />{formatBytes(item.artifactBytes) || "Copy artifact path"}</button> : <small>{item.error || "Build in progress"}</small>}
                  </article>
                ))}
              </div>
            ) : (
              <div className="ios-history-empty"><AppleLogo aria-hidden="true" size={24} weight="regular" /><p>No build receipts yet. Windows compatibility packages and native Mac/Xcode builds are recorded separately here.</p></div>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}
