import { useMemo, useState } from "react";
import { ChartColumn, Check, Moon, RefreshCw, ShieldCheck, SlidersHorizontal, X } from "lucide-react";

import { Button, Icon, Segmented, Spinner, StatusDot } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { placeSession } from "./nxSidebarModel.js";
import { useNightShift } from "./nxNightShiftApi.js";
import { duration } from "./nxNightShiftModel.js";
import { BudgetPanel } from "./NxNightShiftParts.jsx";
import { INITIATIVE, checkLocalOnly, explainSettingsError, refreshSettings, saveSettings } from "./nxSettingsApi.js";

// The Settings cards that talk to the canonical record (T11): how much agents
// do on their own, Night Shift's budget and local-only. NxSettings.jsx lays
// them out with the look, transparency, cleanup and setup cards.

const isAbsolute = path => /^([a-z]:[\\/]|\\\\|\/)/i.test(String(path || ""));
const leaf = path => String(path).split(/[\\/]/).filter(Boolean).pop() || path;
const samePath = (a, b) => String(a).replace(/[\\/]+$/, "").toLowerCase() === String(b).replace(/[\\/]+$/, "").toLowerCase();

function useSave() {
  const [state, setState] = useState({ busy: "", error: null });
  const run = async (key, patch) => {
    setState({ busy: key, error: null });
    try { const data = await saveSettings(patch); setState({ busy: "", error: null }); return data; }
    catch (failure) { setState({ busy: "", error: explainSettingsError(failure) }); return null; }
  };
  return [state, run, () => setState({ busy: "", error: null })];
}

/** Project folders this PC knows (chats with a project folder, and projects made here), most chats first. */
function useProjects(rows) {
  const made = useOs(state => state.projects);
  return useMemo(() => {
    const counts = new Map();
    for (const row of rows) {
      const place = placeSession(row);
      if (place.group === "project" && isAbsolute(place.path)) counts.set(place.path, (counts.get(place.path) || 0) + 1);
    }
    for (const path of Object.keys(made || {})) if (isAbsolute(path) && !counts.has(path)) counts.set(path, 0);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || leaf(a[0]).localeCompare(leaf(b[0]))).map(([path, chats]) => ({ path, chats }));
  }, [rows, made]);
}

export function InitiativeCard({ rows }) {
  const settings = useOs(state => state.prefs?.settings);
  const [{ busy, error }, save] = useSave();
  const [adding, setAdding] = useState("");
  const projects = useProjects(rows);
  const level = settings?.initiative || "suggest";
  const overrides = settings?.projectInitiative || {};
  const overridden = Object.entries(overrides);
  const free = projects.filter(project => !overridden.some(([path]) => samePath(path, project.path)));
  const setOverride = (path, value) => {
    const next = { ...overrides };
    if (value == null) delete next[path]; else next[path] = value;
    return save(`p:${path}`, { projectInitiative: next });
  };
  const current = INITIATIVE.find(option => option.value === level) || INITIATIVE[0];
  return (
    <section id="nx-set-sec-initiative" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-initiative" aria-busy={Boolean(busy)}>
      <header className="nx-ac-head"><div><h3 id="nx-set-initiative">How much agents do on their own</h3>
        <p>For Neyvia's own next steps and housekeeping. Deleting, sending or spending always asks, whatever you pick.</p></div></header>
      <div className="nx-set-row"><span>Everywhere</span>
        <Segmented size="sm" label="Initiative" value={level} onChange={value => void save("level", { initiative: value })}
          options={INITIATIVE.map(({ value, label }) => ({ value, label }))} />
      </div>
      <p className="nx-set-explain">{current.hint}</p>
      <div className="nx-set-sub">
        <strong>Per project</strong>
        {overridden.length ? (
          <ul className="nx-set-list">
            {overridden.map(([path, value]) => (
              <li key={path}>
                <span className="nx-set-path" title={path}>{leaf(path)}<small>{path}</small></span>
                <Segmented size="sm" label={`Initiative in ${leaf(path)}`} value={value} onChange={next => void setOverride(path, next)}
                  options={INITIATIVE.map(({ value: id, label }) => ({ value: id, label }))} />
                <Button size="sm" variant="ghost" icon={X} aria-label={`Use the everywhere setting in ${leaf(path)}`} disabled={busy === `p:${path}`}
                  onClick={() => void setOverride(path, null)}>Reset</Button>
              </li>
            ))}
          </ul>
        ) : <p className="nx-set-hint">Every project follows the setting above.</p>}
        {free.length ? (
          <div className="nx-set-add">
            <label className="nx-set-select">
              <select className="nx-input" aria-label="Project" value={adding} onChange={event => setAdding(event.target.value)}>
                <option value="">Choose a project…</option>
                {free.map(project => <option key={project.path} value={project.path}>{leaf(project.path)}{project.chats ? ` · ${project.chats} chat${project.chats === 1 ? "" : "s"}` : ""}</option>)}
              </select>
            </label>
            <Button size="sm" variant="outline" disabled={!adding || Boolean(busy)}
              onClick={async () => { if (await setOverride(adding, level === "suggest" ? "act-and-tell" : "suggest")) setAdding(""); }}>Set its own level</Button>
          </div>
        ) : null}
      </div>
      {error ? <p className="nx-notice is-error" role="alert">{error.message}</p> : null}
    </section>
  );
}

function budgetFacts(policy) {
  if (!policy) return [];
  const facts = [];
  facts.push(policy.holdAtPlanPercent != null ? `Holds new tasks at ${policy.holdAtPlanPercent}% of a plan limit` : "Doesn't hold for plan limits");
  facts.push(policy.maxNightSeconds ? `${duration(policy.maxNightSeconds)} per night` : "No limit per night");
  facts.push(`${policy.maxConcurrent || 1} task${policy.maxConcurrent === 1 ? "" : "s"} at once`);
  if (policy.maxTaskSeconds) facts.push(`${duration(policy.maxTaskSeconds)} per task`);
  if (policy.maxTaskTokens) facts.push(`${Number(policy.maxTaskTokens).toLocaleString()} tokens per task`);
  const capped = Object.entries(policy.perHarnessBudgets || {}).filter(([, row]) => row && (row.maxTokens || row.maxSeconds)).length;
  if (capped) facts.push(`${capped} agent budget${capped === 1 ? "" : "s"}`);
  if (policy.gpuReservedFor) facts.push("GPU kept for dictation");
  if (policy.quietGpuHours) facts.push(`Quiet GPU ${policy.quietGpuHours.start}–${policy.quietGpuHours.end}`);
  return facts;
}

export function UsageCard() {
  return (
    <section id="nx-set-sec-usage" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-usage">
      <header className="nx-ac-head">
        <div><h3 id="nx-set-usage">Usage</h3><p>Plan windows and resets, tokens by day, agent and model, the API-equivalent value of everything, and what was billed to your API keys.</p></div>
        <Button size="sm" variant="ghost" icon={ChartColumn} onClick={() => os.showPane("usage", "")}>Open Usage</Button>
      </header>
    </section>
  );
}

export function NightShiftCard() {
  const night = useNightShift(true);
  const [open, setOpen] = useState(false);
  const policy = night.policy;
  const facts = budgetFacts(policy);
  const held = policy?.holdAtPlanPercent != null;
  return (
    <section id="nx-set-sec-night" className="nx-ac-card nx-set-card" aria-labelledby="nx-set-night">
      <header className="nx-ac-head">
        <div><h3 id="nx-set-night">Night Shift budget</h3><p>What Night Shift may use while you're away. Checked before every launch and while tasks run.</p></div>
        <Button size="sm" variant="ghost" icon={Moon} onClick={() => os.showPane("mission", "nightshift")}>Open the board</Button>
      </header>
      {night.status === "loading" ? <p className="nx-set-hint"><Spinner size={11} /> Reading the budget…</p> : null}
      {night.status === "offline" || night.status === "error" ? <p className="nx-notice is-error" role="alert">Couldn't read Night Shift: {night.error}</p> : null}
      {policy ? (
        <>
          <div className="nx-set-hold">
            <span className="nx-set-hold-value">{held ? `${policy.holdAtPlanPercent}%` : "Off"}</span>
            <span><strong>Plan hold</strong><small>{held ? "When Codex or Claude Code reaches this much of a plan limit, new tasks wait for the reset, then start on their own." : "New tasks start whatever the plan limits say."}</small></span>
          </div>
          <ul className="nx-set-facts" aria-label="Current budget">
            {policy.paused ? <li className="is-paused">Paused: nothing new starts</li> : null}
            {facts.slice(1).map(fact => <li key={fact}>{fact}</li>)}
          </ul>
          {open ? (
            <BudgetPanel policy={policy} summary={night.summary}
              onSaved={() => { void night.refresh(); void refreshSettings().catch(() => {}); setOpen(false); }} onClose={() => setOpen(false)} />
          ) : <div className="nx-set-row is-actions"><Button size="sm" variant="outline" icon={SlidersHorizontal} onClick={() => setOpen(true)}>Change budget…</Button></div>}
        </>
      ) : null}
    </section>
  );
}

// What each refused attempt in the local-only check is, in plain words.
const CHECK_LABELS = {
  tcp: "Internet connection", connect_ex: "Internet connection (second way)", ipv6: "IPv6 connection", udp: "UDP message",
  dns: "Name lookup (DNS)", http: "Web page (HTTP)", https: "Secure web page (HTTPS)", child: "Starting a program",
  conpty_child: "Starting a terminal program", async_tcp: "Background connection",
};
const PROGRAM_LABELS = {
  "codex.exe": "Codex app server", "node.exe": "Node program", "cmd.exe": "Command window", "python.exe": "Python program (dictation or a tool)",
  "git.exe": "Git", "claude.exe": "Claude Code", "opencode.exe": "OpenCode", "powershell.exe": "PowerShell", "pwsh.exe": "PowerShell",
  subprocess: "A program Neyvia started", "unverified child": "A program Neyvia can't inspect",
};
const programLabel = kind => PROGRAM_LABELS[String(kind || "").toLowerCase()] || kind || "A program";

function programs(children) {
  const counts = new Map();
  for (const child of children || []) counts.set(programLabel(child.kind), (counts.get(programLabel(child.kind)) || 0) + 1);
  return [...counts.entries()];
}

export function PrivacyCard() {
  const prefs = useOs(state => state.prefs);
  const [{ busy, error }, save, clear] = useSave();
  const [check, setCheck] = useState({ status: "idle", result: null, error: "", at: 0 });
  const network = prefs?.network || {};
  const on = Boolean(network.localOnly ?? prefs?.settings?.localOnly);
  const waiting = error?.kind === "children";
  const running = network.activeChildren || 0;
  const toggle = async next => {
    setCheck({ status: "idle", result: null, error: "", at: 0 });
    await save("local", { localOnly: next });
  };
  const runCheck = async () => {
    setCheck({ status: "running", result: null, error: "", at: 0 });
    try {
      const result = await checkLocalOnly();
      setCheck({ status: "done", result, error: "", at: Date.now() });
      void refreshSettings().catch(() => {});
    } catch (failure) { setCheck({ status: "error", result: null, error: explainSettingsError(failure).message, at: 0 }); }
  };
  const checks = check.result?.checks || [];
  const blocked = checks.filter(row => row.blocked).length;
  return (
    <section id="nx-set-sec-privacy" className={`nx-ac-card nx-set-card${on ? " is-local" : ""}`} aria-labelledby="nx-set-privacy" aria-busy={busy === "local"}>
      <header className="nx-ac-head"><div><h3 id="nx-set-privacy">Local-only</h3>
        <p>Keep Neyvia on this PC: no internet, no cloud agents, no new programs. Your chats, notes and files stay readable.</p></div></header>
      <label className="nx-set-switch">
        <span><strong>{on ? "On: nothing leaves this PC" : "Off: agents can use the internet"}</strong>
          <small>{prefs ? (on ? `Enforced by the PC service${network.blockedAttempts ? ` · ${network.blockedAttempts} attempt${network.blockedAttempts === 1 ? "" : "s"} blocked so far` : ""}` : "Cloud agents, web search and add-on downloads work.") : "Reading…"}</small></span>
        <input type="checkbox" role="switch" aria-label="Local-only" checked={on} disabled={!prefs || busy === "local"} onChange={event => void toggle(event.target.checked)} />
      </label>
      {waiting ? (
        <div className="nx-set-wait" role="status">
          <p>{running ? error.message : "They've stopped. You can turn local-only on now."}</p>
          {running ? (
            <ul className="nx-set-programs">{programs(network.children).map(([label, count]) => <li key={label}><StatusDot tone="live" />{label}{count > 1 ? ` ×${count}` : ""}</li>)}</ul>
          ) : null}
          {running ? <p className="nx-set-hint">Finish or close the chats using them. Some, like the Codex app server, keep running while Neyvia shows Codex chats. This list updates on its own.</p> : null}
          <div className="nx-set-row is-actions">
            <Button size="sm" variant={running ? "outline" : "primary"} icon={RefreshCw} onClick={() => void toggle(true)}>Try again</Button>
            <Button size="sm" variant="ghost" onClick={clear}>Not now</Button>
          </div>
        </div>
      ) : error ? <p className="nx-notice is-error" role="alert">{error.message}</p> : null}
      {on ? (
        <div className="nx-set-check">
          <div className="nx-set-row">
            <span>Prove it<small className="nx-set-hint">Neyvia really tries to reach the internet and start programs, and shows what was stopped.</small></span>
            <Button size="sm" variant="outline" icon={ShieldCheck} disabled={check.status === "running"} onClick={() => void runCheck()}>
              {check.status === "running" ? "Checking…" : check.status === "done" ? "Check again" : "Check it's blocking"}</Button>
          </div>
          {check.status === "error" ? <p className="nx-notice is-error" role="alert">{check.error}</p> : null}
          {check.status === "done" ? (
            <div className="nx-set-result" role="status">
              <strong className={blocked === checks.length ? "is-ok" : "is-bad"}>
                {blocked === checks.length ? `All ${checks.length} attempts were blocked` : `${checks.length - blocked} of ${checks.length} attempts got through`}
                <small> · {new Date(check.at).toLocaleTimeString()}</small></strong>
              <ul>{checks.map(row => (
                <li key={row.name} className={row.blocked ? "is-ok" : "is-bad"}>
                  <Icon as={row.blocked ? Check : X} size={13} /><span>{CHECK_LABELS[row.name] || row.name}</span><em>{row.blocked ? "Blocked" : "Got through"}</em>
                </li>
              ))}</ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

