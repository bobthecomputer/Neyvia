import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Download, Pause, Play, RefreshCw, RotateCcw, TriangleAlert, Wrench } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { PacksSection } from "./NxOnboardingPacks.jsx";
import { componentGroups, componentView, essentialsView, interestsFor, recommend, toggle } from "./nxOnboardingModel.js";

// The downloads step. Four groups, each saying what it is, what it unlocks and its state:
//   Core (always on), Claude Code mod, Codex skills, Optional packs.
// The two mods are switches over components_status_command / components_install_command /
// components_remove_command / components_update_command (src/grant_agent/components.py, config/components.json).
// Nothing is changed on this PC until a switch is turned on, and each switch says where it writes.

/** Status of every component, plus the action calls. `rows` is null until the first answer. */
export function useComponents(open) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState({});
  const [notes, setNotes] = useState({});

  const merge = useCallback(next => setRows(current => {
    const list = current || [];
    const incoming = Array.isArray(next) ? next : [next];
    const byId = new Map(list.map(row => [row.id, row]));
    for (const row of incoming) if (row?.id) byId.set(row.id, { ...(byId.get(row.id) || {}), ...row });
    return [...byId.values()];
  }), []);

  const refresh = useCallback(() => callNx("components_status_command")
    .then(result => { setRows(result?.components || []); setError(""); })
    .catch(failure => { setRows(current => current || []); setError(failure?.message || "Download status didn't load."); }), []);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);

  const run = useCallback(async (component, action, payload = {}) => {
    setBusy(current => ({ ...current, [component]: action }));
    setNotes(current => ({ ...current, [component]: "" }));
    try {
      const result = await callNx(`components_${action}_command`, { component, ...payload });
      if (result?.state) merge(result.state); else await refresh();
      if (result?.ok === false) setNotes(current => ({ ...current, [component]: result.detail || result.error || "That didn't finish." }));
      return result;
    } catch (failure) {
      setNotes(current => ({ ...current, [component]: failure?.message || "That didn't finish." }));
      return null;
    } finally {
      setBusy(current => ({ ...current, [component]: "" }));
    }
  }, [merge, refresh]);

  return { rows, error, busy, notes, refresh, run };
}

function Switch({ on, disabled, label, onChange }) {
  return (
    <label className={`nx-onb-switch${on ? " is-on" : ""}${disabled ? " is-disabled" : ""}`}>
      <input type="checkbox" role="switch" aria-label={label} checked={on} disabled={disabled} onChange={event => onChange(event.target.checked)} />
      <span aria-hidden="true" />
    </label>
  );
}

/** The two mods: one card each, a switch, the state in words and the unlock line. */
function ModCard({ id, mark, row, busy, note, onRun }) {
  const view = componentView(row, busy);
  const unlocks = row?.unlocks || [];
  const needs = row?.needs || [];
  const unmanaged = row?.unmanaged || [];
  return (
    <article className={`nx-onb-mod is-${view.state}${view.on ? " is-on" : ""}`} data-component={id}>
      <header>
        <span className="nx-onb-mod-mark"><ProviderMark id={mark} size={22} /></span>
        <div className="nx-onb-mod-title">
          <b>{row?.title || id}</b>
          <small className={`is-${view.tone}`}>{view.busy ? <><Spinner size={11} /> {view.detail}</> : view.detail}</small>
        </div>
        <Switch on={view.on} disabled={!view.canToggle} label={row?.title || id}
          onChange={next => void onRun(id, next ? "install" : "remove")} />
      </header>
      <p>{row?.summary}</p>
      {unlocks.length ? <ul className="nx-onb-unlocks" aria-label="What it unlocks">{unlocks.map(text => <li key={text}><Icon as={Check} size={12} /> {text}</li>)}</ul> : null}
      {view.state === "unavailable" && needs.length ? <p className="nx-onb-fine">Needs: {needs.join(", ")}.</p> : null}
      {unmanaged.length && !view.installed ? (
        <div className="nx-onb-adopt">
          <p>{unmanaged.length === 1 ? "A skill with the same name is already there" : `${unmanaged.length} skills with the same names are already there`}. Replace {unmanaged.length === 1 ? "it" : "them"} and keep the old {unmanaged.length === 1 ? "copy" : "copies"} in a backup folder?</p>
          <Button variant="outline" size="sm" icon={RotateCcw} disabled={view.busy} onClick={() => void onRun(id, "install", { adopt: true })}>Replace and keep a backup</Button>
        </div>
      ) : null}
      {note ? <p className="nx-onb-error"><Icon as={TriangleAlert} size={14} /> {note}</p> : null}
      <footer>
        <small>{row?.updatePath}</small>
        {view.canUpdate ? <Button variant="outline" size="sm" icon={RefreshCw} onClick={() => void onRun(id, "update")}>Update</Button> : null}
        {view.canRepair ? <Button variant="outline" size="sm" icon={Wrench} onClick={() => void onRun(id, "install")}>Repair</Button> : null}
      </footer>
    </article>
  );
}

/** Core: the base pack (with its download controls), then the other always-on rows. */
function CoreGroup({ basePack, onBasePack, rows }) {
  const view = essentialsView(basePack);
  const act = async command => { try { onBasePack(await callNx(command)); } catch (failure) { onBasePack({ ...basePack, state: "failed", error: failure?.message || "The download could not start." }); } };
  return (
    <section className="nx-onb-group" aria-labelledby="nx-onb-core">
      <h3 id="nx-onb-core" className="nx-onb-sub">Core <span className="nx-onb-tag">Always on</span></h3>
      <div className="nx-onb-corelist">
        <div className={`nx-onb-core is-${view.state}`}>
          <span className="nx-onb-core-icon">{view.state === "done" ? <Icon as={Check} size={14} /> : view.state === "failed" ? <Icon as={TriangleAlert} size={14} /> : view.busy ? <Spinner size={13} /> : <Icon as={Download} size={14} />}</span>
          <span className="nx-onb-core-name"><b>The Neyvia app</b><small>{view.headline}{view.state === "done" ? "" : ` · ${view.detail}`}</small></span>
          {view.busy ? <Button variant="ghost" size="sm" icon={Pause} onClick={() => void act("onboarding_base_pack_pause_command")}>Pause</Button> : null}
          {view.state === "paused" || view.state === "idle" ? <Button variant="outline" size="sm" icon={Play} onClick={() => void act("onboarding_base_pack_start_command")}>{view.state === "idle" ? "Start" : "Resume"}</Button> : null}
          {view.state === "failed" ? <Button variant="outline" size="sm" icon={RotateCcw} onClick={() => void act("onboarding_base_pack_start_command")}>Try again</Button> : null}
          {view.busy ? <div className="nx-onb-meter" role="progressbar" aria-label="Essentials download" aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.percent}><i style={{ width: `${view.percent}%` }} /></div> : null}
        </div>
        {rows.map(row => {
          const v = componentView(row);
          return (
            <div key={row.id} className="nx-onb-core">
              <span className="nx-onb-core-icon"><Icon as={v.state === "broken" ? TriangleAlert : Check} size={14} /></span>
              <span className="nx-onb-core-name"><b>{row.title}</b><small>{row.summary}</small></span>
              <span className="nx-onb-core-state">{v.state === "current" ? `v${String(row.installedVersion || "").replace(/^v/, "")}` : v.state === "update-available" ? "Update ready" : v.state === "broken" ? "Needs repair" : ""}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

/** Things Neyvia only version-checks tonight: shown as facts, not as switches. */
function Parts({ rows }) {
  if (!rows.length) return null;
  return (
    <details className="nx-onb-more nx-onb-parts">
      <summary>Parts that update with Neyvia · {rows.length}</summary>
      <ul>
        {rows.map(row => {
          const v = componentView(row);
          return <li key={row.id}><b>{row.title}</b><small>{row.summary}</small><em>{v.state === "check-only" || v.state === "current" ? v.detail.split(" · ")[0] : "Not found"}</em></li>;
        })}
      </ul>
    </details>
  );
}

/** What each pack unlocks, from the interests that recommend it. */
function packUnlocks(catalog) {
  const map = {};
  for (const interest of catalog?.interests || []) for (const id of interest.packs || []) (map[id] ||= []).push(interest.label);
  return map;
}

// Words for the two switches before the PC answers, and when an older PC service does not know the command.
const MOD_COPY = {
  "claude-mod": {
    id: "claude-mod", group: "claude-mod", title: "Add Neyvia to my Claude Code",
    summary: "Installs Neyvia's plugin into your own Claude Code: Neyvia's tools, manuals and live status, on your plan limits.",
    unlocks: ["Claude Code driven and watched from Neyvia", "Neyvia tools inside Claude Code"], needs: ["Claude Code installed on this PC"],
    updatePath: "Refreshed with each Neyvia update; run /reload-plugins in a running Claude Code, or restart it.",
  },
  "codex-skills": {
    id: "codex-skills", group: "codex-skills", title: "Neyvia skills for Codex",
    summary: "Copies Neyvia's Codex skills into your Codex skills folder as neyvia-* and keeps them current. Your own skills are never touched.",
    unlocks: ["Neyvia's PDF, image and design skills inside Codex"], needs: ["Codex installed on this PC"],
    updatePath: "Refreshed with each Neyvia update. Only folders Neyvia installed are changed.",
  },
};
const withCopy = (row, id, loaded) => row || { ...MOD_COPY[id], actions: [], state: loaded ? "unavailable" : "unknown", detail: loaded ? "This version of the PC service can't manage it yet. Update Neyvia, then come back." : "" };

export function DownloadsStep({ data, picks, setPicks, packState, components, basePack, onBasePack }) {
  const { rows, error, busy, notes, run } = components;
  const groups = useMemo(() => componentGroups(rows), [rows]);
  const { catalog } = data;
  const chosen = interestsFor(catalog, picks);
  const suggested = recommend(catalog, chosen);
  const packs = useMemo(() => Object.fromEntries(data.packs.map(pack => [pack.id, pack])), [data.packs]);
  const unlocks = useMemo(() => packUnlocks(catalog), [catalog]);

  const applyInterests = interests => {
    const before = recommend(catalog, interestsFor(catalog, picks));
    const after = recommend(catalog, interestsFor(catalog, { interests, tier: "" }));
    // Recommendations follow the interests; what the person added or removed by hand stays.
    const follow = (list, was, now) => [...list.filter(id => !was.includes(id) || now.includes(id)), ...now.filter(id => !was.includes(id) && !list.includes(id))];
    setPicks({ ...picks, tier: "", interests, apps: follow(picks.apps, before.apps, after.apps) });
  };

  return (
    <div className="nx-onb-step is-wide">
      <div className="nx-onb-step-head">
        <h2 id="nx-onb-title">Choose what to download</h2>
        <p>Core is on. The rest is optional, one switch each, and every part keeps itself current.</p>
      </div>
      {error ? <p className="nx-onb-error"><Icon as={TriangleAlert} size={14} /> {error}</p> : null}
      {!rows && !error ? <div className="nx-onb-loading"><Spinner size={16} /> Checking this PC…</div> : null}
      <CoreGroup basePack={basePack} onBasePack={onBasePack} rows={groups.core} />
      <section className="nx-onb-group" aria-labelledby="nx-onb-mods">
        <h3 id="nx-onb-mods" className="nx-onb-sub">For the agents you already use <span className="nx-onb-tag">Off until you turn it on</span></h3>
        <div className="nx-onb-mods">
          <ModCard id="claude-mod" mark="claude" row={withCopy(groups.claudeMod, "claude-mod", Boolean(rows))} busy={busy["claude-mod"]} note={notes["claude-mod"]} onRun={run} />
          <ModCard id="codex-skills" mark="codex" row={withCopy(groups.codexSkills, "codex-skills", Boolean(rows))} busy={busy["codex-skills"]} note={notes["codex-skills"]} onRun={run} />
        </div>
      </section>
      <section className="nx-onb-group" aria-labelledby="nx-onb-optional">
        <h3 id="nx-onb-optional" className="nx-onb-sub">Optional packs</h3>
        <p className="nx-onb-fine">Nothing downloads on its own.</p>
        <div className="nx-onb-chips" role="group" aria-label="What you will use Neyvia for">
          {catalog.interests.map(row => {
            const on = chosen.includes(row.id);
            return <button key={row.id} type="button" className={`nx-onb-chip${on ? " is-on" : ""}`} aria-pressed={on} title={row.hint} onClick={() => applyInterests(toggle(chosen, row.id))}>{on ? <Icon as={Check} size={12} /> : null}{row.label}</button>;
          })}
        </div>
        <PacksSection packs={data.packs} suggested={suggested.packs.filter(id => packs[id])} statuses={packState.statuses} error={packState.error} unlocks={unlocks}
          onInstall={id => { packState.install(id); setPicks({ ...picks, packs: [...new Set([...picks.packs, id])] }); }} />
        <Parts rows={groups.optional} />
      </section>
    </div>
  );
}
