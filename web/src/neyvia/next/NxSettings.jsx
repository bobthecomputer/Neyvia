import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { CirclePlay, Compass, Leaf as LeafIcon } from "lucide-react";

import "./nxAccounts.css";
import "./nxSidebar.css";
import "./nxSettings.css";
import { Button, Segmented } from "./nxPrimitives.jsx";
import { DENSITIES, THEME_TO_SETTINGS, getOs, os, useOs } from "./nxOsStore.js";
import { NxThemePicker } from "./NxThemePicker.jsx";
import { DEFAULT_CLEANUP } from "./nxSidebarModel.js";
import { callTool } from "./nxBus.js";
import { CleanupForm, TidyPreview, undoLastTidy, useTidy } from "./NxTidy.jsx";
import { TRANSPARENCY_LABELS, TRANSPARENCY_LEVELS } from "./nxTransparencyModel.js";
import { explainSettingsError, reenterSetup, saveSettings, useSettingsPoll } from "./nxSettingsApi.js";
import { VoiceCard } from "./NxVoiceSettings.jsx";
import { InitiativeCard, NightShiftCard, PrivacyCard, UsageCard } from "./NxSettingsParts.jsx";
import { UpdateCard } from "./NxUpdate.jsx";
import { NeyviaPromptEditorDialog } from "../NeyviaPromptEditorDialog.jsx";
import { callNx } from "./nxApi.js";
// The typeface and background pickers load with this page, not with the shell.
const LookControls = lazy(() => import("./NxLook.jsx").then(module => ({ default: module.LookControls })));

// Settings (the "settings" stage pane), one page: the look, how much agents
// do on their own and how much of their thinking shows, Night Shift's budget,
// local-only, chat cleanup and setup. Theme, density, initiative, cleanup,
// Night Shift and local-only are the PC service's canonical record (T11,
// nxSettingsApi); ambient light and reduced motion belong to this screen.
// target "tidy" opens straight into the tidy preview; other targets
// ("look", "agents", "night", "privacy", "cleanup", "setup") scroll there.

const DENSITY_LABELS = { calm: "Calm", workshop: "Workshop", grove: "Grove" };
const DENSITY_HINTS = {
  calm: "Just the chat. Side panels stay closed until you open them.",
  workshop: "The chat with its panels beside it.",
  grove: "Everything at once, with the activity rail.",
};
const SECTIONS = [
  { id: "look", label: "Look" },
  { id: "agents", label: "Agents" },
  { id: "prompts", label: "Prompts" },
  { id: "voice", label: "Voice" },
  { id: "night", label: "Night Shift" },
  { id: "privacy", label: "Local-only" },
  { id: "cleanup", label: "Cleanup" },
  { id: "setup", label: "Setup" },
  { id: "updates", label: "Updates" },
];
const SECTION_ANCHOR = { look: "look", agents: "initiative", prompts: "prompts", voice: "voice", night: "night", privacy: "privacy", cleanup: "cleanup", tidy: "cleanup", setup: "setup" };

function PromptsCard() {
  const [editing, setEditing] = useState(false);
  return <section id="nx-set-sec-prompts" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-prompts">
    <header className="nx-ac-head"><div><h3 id="nx-set-prompts">System prompts</h3><p>Edit the instructions used by your agents. Import a text or Markdown file, review it, then save.</p></div></header>
    <Button variant="outline" size="sm" onClick={() => setEditing(true)}>Edit system prompts</Button>
    {editing ? <NeyviaPromptEditorDialog callBackend={callNx} onClose={() => setEditing(false)} /> : null}
  </section>;
}

/** What the last tidy archived (by hand or automatically), so it can be put back later. */
function useLastArchive(archivedCount) {
  const [last, setLast] = useState(null);
  const refresh = useCallback(() => {
    callTool("neyvia.sidebar.policy", {}).then(receipt => setLast(receipt.result?.lastArchive || null)).catch(() => {});
  }, []);
  useEffect(() => {
    refresh();
    window.addEventListener("nx:tidy-changed", refresh);
    return () => window.removeEventListener("nx:tidy-changed", refresh);
  }, [refresh, archivedCount]); // an automatic tidy shows up as more archived chats
  return last;
}

function CleanupCard({ rows, tidyFirst }) {
  const archivedCount = rows.filter(row => row.archived).length;
  const last = useLastArchive(archivedCount);
  const saved = useOs(state => state.cleanup);
  const policy = useMemo(() => (saved ? { ...DEFAULT_CLEANUP, ...saved } : DEFAULT_CLEANUP), [saved]);
  const [previewing, setPreviewing] = useState(tidyFirst);
  const tidy = useTidy();
  useEffect(() => { if (tidyFirst) setPreviewing(true); }, [tidyFirst]);
  return (
    <section id="nx-set-sec-cleanup" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-cleanup">
      <header className="nx-ac-head">
        <div>
          <h3 id="nx-set-cleanup">Chat cleanup</h3>
          <p>Old chats fall into Fallen leaves so the sidebar stays short. Nothing is deleted{archivedCount ? `; ${archivedCount} chat${archivedCount === 1 ? " is" : "s are"} there now` : ""}.</p>
        </div>
        {previewing ? null : <Button variant="outline" size="sm" icon={LeafIcon} onClick={() => setPreviewing(true)}>Tidy now…</Button>}
      </header>
      {previewing ? (
        <div className="nx-set-tidy"><TidyPreview rows={rows} tidy={tidy} onClose={() => { setPreviewing(false); tidy.reset(); }} /></div>
      ) : null}
      {last?.archived?.length ? (
        <div className="nx-set-last">
          <span>Last tidy{last.automatic ? " (automatic)" : ""}: {last.archived.length} chat{last.archived.length === 1 ? "" : "s"} archived{last.at ? ` · ${new Date(last.at * 1000).toLocaleString()}` : ""}</span>
          <Button size="sm" variant="ghost" onClick={() => void undoLastTidy()}>Put them back</Button>
        </div>
      ) : null}
      <div className="nx-cleanup nx-set-rules"><CleanupForm policy={policy} /></div>
    </section>
  );
}

function LookCard() {
  const theme = useOs(state => state.theme);
  const density = useOs(state => state.density);
  const ambient = useOs(state => state.ambient);
  const rain = useOs(state => state.rain);
  const motion = useOs(state => state.motion);
  const [error, setError] = useState("");
  // Shown at once, then saved on the PC; a refusal puts the saved look back.
  const change = async (apply, patch) => {
    setError("");
    apply();
    try { await saveSettings(patch); }
    catch (failure) {
      setError(explainSettingsError(failure).message);
      const prefs = getOs().prefs;
      if (prefs) os.setPrefs(prefs);
    }
  };
  return (
    <section id="nx-set-sec-look" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-look">
      <header className="nx-ac-head"><div><h3 id="nx-set-look">Look</h3><p>Theme, typeface, text size, background and how much the screen shows at once. Saved on this PC, so every window and device matches.</p></div></header>
      <div className="nx-set-row nx-set-row-stack"><span>Theme</span>
        <NxThemePicker value={theme} onChange={id => void change(() => os.setTheme(id), { theme: THEME_TO_SETTINGS[id] })} />
      </div>
      {theme === "terminal" ? (
        <div className="nx-set-row"><span>Matrix rain<small className="nx-set-hint">Falling characters in the margins of the Terminal theme. Never under the conversation; off when motion is reduced</small></span>
          <Segmented size="sm" label="Matrix rain" value={rain ? "on" : "off"} onChange={value => os.setRain(value === "on")}
            options={[{ value: "off", label: "Off" }, { value: "on", label: "On" }]} />
        </div>
      ) : null}
      <Suspense fallback={<p className="nx-set-hint">Loading typefaces and backgrounds…</p>}><LookControls /></Suspense>
      <div className="nx-set-row"><span>Density<small className="nx-set-hint">{DENSITY_HINTS[density]}</small></span>
        <Segmented size="sm" label="Density" value={density} onChange={id => void change(() => os.setDensity(id), { density: id })}
          options={DENSITIES.map(id => ({ value: id, label: DENSITY_LABELS[id] || id }))} />
      </div>
      <div className="nx-set-row"><span>Ambient light<small className="nx-set-hint">Soft light behind the chat that warms up while an agent works</small></span>
        <Segmented size="sm" label="Ambient light" value={ambient ? "on" : "off"} onChange={value => os.setAmbient(value === "on")}
          options={[{ value: "on", label: "On" }, { value: "off", label: "Off" }]} />
      </div>
      <div className="nx-set-row"><span>Motion<small className="nx-set-hint">Reduce keeps fades and drops slides and springs</small></span>
        <Segmented size="sm" label="Motion" value={motion === "reduce" ? "reduce" : "system"} onChange={os.setMotion}
          options={[{ value: "system", label: "Follow Windows" }, { value: "reduce", label: "Reduce" }]} />
      </div>
      {error ? <p className="nx-notice is-error" role="alert">{error}</p> : null}
      <p className="nx-set-hint">Ambient light and motion apply to this screen. Keyboard shortcuts and voice commands: press <kbd className="nx-kbd">Ctrl /</kbd>.</p>
    </section>
  );
}

function TransparencyCard() {
  const level = useOs(state => state.transparency);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = async next => {
    if (busy || next === level) return;
    setBusy(true); setError("");
    try {
      await callTool("neyvia.view.transparency", { level: next });
      os.setTransparency(next);
    } catch (failure) { setError(failure?.message || "This setting couldn’t be saved. Try again."); }
    finally { setBusy(false); }
  };
  return <section className="nx-ac-card nx-set-card" aria-labelledby="nx-set-transparency" aria-busy={busy}>
    <header className="nx-ac-head"><div><h3 id="nx-set-transparency">Thinking and actions</h3><p>Choose how much each chat shows. Every agent app uses the same view.</p></div></header>
    <div className="nx-set-row"><span>Detail</span>
      <Segmented size="sm" label="Thinking and actions" value={level} onChange={change} options={TRANSPARENCY_LEVELS.map(value => ({ value, label: TRANSPARENCY_LABELS[value] }))} />
    </div>
    <p className="nx-set-hint">Show everything opens shared thinking, full commands, arguments, results and file changes. Summaries keeps them a click away. Minimal keeps messages, errors and notices.</p>
    {error ? <p className="nx-notice is-error" role="alert">{error}</p> : null}
  </section>;
}

function SetupCard() {
  const [state, setState] = useState({ busy: false, error: "" });
  const setup = useOs(s => s.prefs?.setup);
  const reenter = async () => {
    setState({ busy: true, error: "" });
    try { await reenterSetup(); setState({ busy: false, error: "" }); }
    catch (failure) { setState({ busy: false, error: explainSettingsError(failure).message }); }
  };
  return (
    <section id="nx-set-sec-setup" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-setup">
      <header className="nx-ac-head">
        <div><h3 id="nx-set-setup">Setup and tour</h3><p>Go through setup again: downloads, the Claude Code mod, Codex skills and connections. What you installed and signed in to stays.</p></div>
      </header>
      <div className="nx-set-row is-actions">
        <Button variant="outline" size="sm" icon={Compass} disabled={state.busy} onClick={() => void reenter()}>{state.busy ? "Opening…" : "Re-enter setup"}</Button>
        <Button variant="ghost" size="sm" icon={CirclePlay} onClick={() => os.openOnboarding("unique", "unique")}>What makes Neyvia different</Button>
        <Button variant="ghost" size="sm" icon={CirclePlay} onClick={() => os.openOnboarding("tour", "tour")}>Replay the full tour</Button>
      </div>
      {setup?.requestedAt ? <p className="nx-set-hint">Setup last reopened {new Date(setup.requestedAt).toLocaleString()}.</p> : null}
      {state.error ? <p className="nx-notice is-error" role="alert">{state.error}</p> : null}
    </section>
  );
}

function ToolUpdatesCard() {
  const policy = useOs(state => state.prefs?.settings?.toolAutoUpdate || "allow");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = async next => {
    setBusy(true); setError("");
    try { await saveSettings({ toolAutoUpdate: next }); }
    catch (failure) { setError(explainSettingsError(failure).message); }
    finally { setBusy(false); }
  };
  return <section className="nx-ac-card nx-set-card" aria-labelledby="nx-set-tool-updates" aria-busy={busy}>
    <header className="nx-ac-head"><div><h3 id="nx-set-tool-updates">Tool updates</h3><p>Choose whether Neyvia may update your globally installed command-line tools.</p></div></header>
    <label className="nx-set-row"><span>Global CLI updates</span><select className="nx-input" aria-label="Global CLI updates" value={policy} disabled={busy} onChange={event => void change(event.target.value)}><option value="ask">Ask first</option><option value="off">Off</option><option value="allow">Allow automatic updates</option></select></label>
    <p className="nx-set-hint">Development and scratch workspaces never update global tools. Local-only also blocks updates. Results appear in activity.</p>
    {error ? <p className="nx-notice is-error" role="alert">{error}</p> : null}
  </section>;
}

function SectionNav() {
  const jump = id => document.getElementById(`nx-set-sec-${SECTION_ANCHOR[id] || id}`)?.scrollIntoView({ behavior: getOs().motion === "reduce" ? "auto" : "smooth", block: "start" });
  return (
    <nav className="nx-set-nav" aria-label="Settings sections">
      {SECTIONS.map(section => <button key={section.id} type="button" onClick={() => jump(section.id)}>{section.label}</button>)}
    </nav>
  );
}

export function NxSettings({ target, rows = [] }) {
  const pollError = useSettingsPoll(true);
  const prefs = useOs(state => state.prefs);
  useEffect(() => {
    const anchor = SECTION_ANCHOR[target];
    if (anchor) requestAnimationFrame(() => document.getElementById(`nx-set-sec-${anchor}`)?.scrollIntoView({ block: "start" }));
  }, [target]);
  return (
    <div className="nx-ac nx-scroll nx-set">
      <div className="nx-ac-inner">
        <SectionNav />
        {pollError && !prefs ? <p className="nx-notice is-error" role="alert">{pollError.message}</p> : null}
        <LookCard />
        <InitiativeCard rows={rows} />
        <PromptsCard />
        <VoiceCard />
        <TransparencyCard />
        <UsageCard />
        <NightShiftCard />
        <PrivacyCard />
        <ToolUpdatesCard />
        <UpdateCard />
        <CleanupCard rows={rows} tidyFirst={target === "tidy"} />
        <SetupCard />
      </div>
    </div>
  );
}
