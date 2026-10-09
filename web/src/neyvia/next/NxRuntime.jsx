import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { BookOpen, ChevronDown, ChevronRight, RefreshCw, TriangleAlert } from "lucide-react";

import { backendBase, callNx } from "./nxApi.js";
import { ProviderMark, PROVIDER_MARKS, resolveProviderMarkId } from "./ProviderMark.jsx";
import { CEILINGS, mergeRuntimes, runtimeSummary } from "./nxRuntimeModel.js";
import { Button, Icon, IconButton, Segmented, Spinner, StatusDot } from "./nxPrimitives.jsx";
import { NxConnections } from "./NxConnections.jsx";
import "./nxPanes.css";

// The Runtime page (pane.show {kind: "runtime"}, launcher "Runtimes", strip):
// every coding harness Neyvia knows, whether it is on this PC, its version,
// whether Neyvia can start chats with it; each row opens to its models,
// sign-in and the permission ceiling Paul allows. Ceilings and allowed models
// save through POST /api/ui/runtime and apply to new turns.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function runtimeApi(body) {
  const response = await fetch(`${base()}/api/ui/runtime`, body ? {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : { credentials: "include" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `Runtime check failed (HTTP ${response.status})`);
  return result?.data ?? result;
}

const MODEL_PREVIEW = 12;
// The last check, kept so reopening the page is instant; "Check again" refreshes.
let lastCatalog = null;
let lastMatrix = null;

// The last reading, shared with the strip.
let reading = null;
const listeners = new Set();
function publish(next) { reading = next; listeners.forEach(listener => listener()); }
export function useRuntimeReading() {
  return useSyncExternalStore(listener => { listeners.add(listener); return () => listeners.delete(listener); }, () => reading);
}

function Row({ row, open, onToggle, onSaved }) {
  const [ceiling, setCeiling] = useState(row.ceiling);
  const [allowed, setAllowed] = useState(row.allowedModels);
  const [save, setSave] = useState({ status: "idle" });
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  useEffect(() => { setCeiling(row.ceiling); setAllowed(row.allowedModels); }, [row.ceiling, row.allowedModels]);
  const needle = filter.trim().toLowerCase();
  const matching = row.models.filter(model => !needle || `${model.id} ${model.label || ""}`.toLowerCase().includes(needle));
  // Allowed and default models first, so a long list still shows what matters.
  const saved = row.allowedModels;
  const ordered = [...matching].sort((a, b) => Number(saved.includes(b.id)) - Number(saved.includes(a.id)) || Number(Boolean(b.default)) - Number(Boolean(a.default)));
  const models = all || needle ? ordered : ordered.slice(0, MODEL_PREVIEW);
  const changed = ceiling !== row.ceiling || allowed.join("|") !== row.allowedModels.join("|");
  const store = async () => {
    setSave({ status: "saving" });
    try {
      const result = await runtimeApi({ action: "policy", app: row.policyId, permissionCeiling: ceiling, allowedModels: allowed });
      setSave({ status: "saved" });
      onSaved(result.policies);
    } catch (error) { setSave({ status: "error", error: error.message }); }
  };
  const markId = resolveProviderMarkId(row.id) || resolveProviderMarkId(row.name);
  return (
    <li className={`nx-rt-row${open ? " is-open" : ""}`}>
      <button type="button" className="nx-rt-line" aria-expanded={open} onClick={onToggle}>
        <Icon as={open ? ChevronDown : ChevronRight} size={14} />
        <span className="nx-rt-name">
          <span className="nx-rt-mark"><ProviderMark id={markId} size={16} /></span>
          {markId && row.name === row.id ? PROVIDER_MARKS[markId].label : row.name}
        </span>
        <span className="nx-rt-cell">{row.installed ? "Found" : "Not found"}</span>
        <span className="nx-rt-cell nx-rt-mono" title={row.version}>{row.version || "—"}</span>
        <span className="nx-rt-cell">{row.mode}</span>
        <span className="nx-rt-cell">{row.starts ? "Yes" : "No"}</span>
        <span className="nx-rt-cell nx-rt-status"><StatusDot tone={row.tone} />{row.status}</span>
      </button>
      {open ? (
        <div className="nx-rt-detail">
          {row.description ? <p className="nx-rt-about">{row.description}</p> : null}
          {row.reason ? <p className="nx-rt-reason"><Icon as={TriangleAlert} size={13} />{row.reason}</p> : null}
          <dl className="nx-rt-facts">
            <dt>Sign-in</dt><dd>{row.auth}{row.authHint ? <small>{row.authHint}</small> : null}</dd>
            <dt>Default model</dt><dd>{row.defaultModel || "—"}{row.modelPolicy ? <small>{row.modelPolicy}</small> : null}</dd>
            <dt>Neyvia can</dt><dd>{row.can.length ? row.can.join(", ") : "Nothing yet: no connected adapter"}</dd>
            {row.command ? <><dt>Program</dt><dd className="nx-rt-mono">{row.command}</dd></> : null}
          </dl>
          <section className="nx-rt-block" aria-label="Models">
            <h4>
              Models {row.models.length ? <span>{row.models.length}</span> : null}
              {row.models.length > MODEL_PREVIEW ? (
                <input className="nx-rt-filter" type="search" placeholder="Find a model" value={filter} aria-label={`Find a ${row.name} model`}
                  onChange={event => setFilter(event.target.value)} />
              ) : null}
            </h4>
            {row.models.length ? (
              <ul className="nx-rt-models">
                {models.map(model => (
                  <li key={model.id}>
                    {row.policyId ? (
                      <label>
                        <input type="checkbox" checked={allowed.includes(model.id)}
                          onChange={event => setAllowed(current => (event.target.checked ? [...current, model.id] : current.filter(id => id !== model.id)))} />
                        <span>{model.label || model.id}</span>
                      </label>
                    ) : <span>{model.label || model.id}</span>}
                    {model.default ? <em>default</em> : null}
                    {model.efforts?.length ? <small>{model.efforts.join(" · ")}</small> : null}
                  </li>
                ))}
              </ul>
            ) : <p className="nx-rt-muted">{row.modelError || (row.starts ? "This runtime didn't list its models." : "Models show once Neyvia is connected to it.")}</p>}
            {!needle && row.models.length > MODEL_PREVIEW ? (
              <Button size="sm" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${row.models.length}`}</Button>
            ) : null}
            {row.policyId && row.models.length ? <p className="nx-rt-muted">Tick models to allow only those. None ticked means any model.</p> : null}
          </section>
          {row.policyId ? (
            <section className="nx-rt-block" aria-label="Permission ceiling">
              <h4>Permission ceiling</h4>
              <p className="nx-rt-muted">The most a chat with {row.name} may do on this PC. New turns above it are refused.</p>
              <div className="nx-rt-save">
                <Segmented size="sm" label="Permission ceiling" value={ceiling} onChange={setCeiling} options={CEILINGS} />
                {!row.ceiling ? <span className="nx-rt-muted">No ceiling set</span> : null}
                <span className="nx-head-spacer" />
                {save.status === "saved" && !changed ? <span className="nx-rt-ok">Saved</span> : null}
                {save.status === "error" ? <span className="nx-rt-err">{save.error}</span> : null}
                <Button size="sm" variant="primary" disabled={!changed || !ceiling || save.status === "saving"} onClick={() => void store()}>
                  {save.status === "saving" ? "Saving…" : "Save"}
                </Button>
              </div>
            </section>
          ) : null}
          {row.capabilities.length ? (
            <section className="nx-rt-block" aria-label="What it offers">
              <h4>What it offers</h4>
              <ul className="nx-rt-caps">
                {row.capabilities.map(item => <li key={item.key} className={item.available ? "is-on" : ""}><StatusDot tone={item.available ? "green" : "idle"} />{item.label}</li>)}
              </ul>
            </section>
          ) : null}
          {row.docsUrl ? <a className="nx-btn nx-btn-ghost nx-btn-sm" href={row.docsUrl} target="_blank" rel="noreferrer"><Icon as={BookOpen} size={14} />Docs</a> : null}
        </div>
      ) : null}
    </li>
  );
}

function SelfCheck({ check }) {
  if (!check || check.state === "unknown") return null;
  const state = check.state;
  const tone = state === "passed" ? "green" : state === "running" ? "idle" : "red";
  const [all, setAll] = useState(false);
  const failures = Array.isArray(check.failures) ? check.failures : [];
  const shownFailures = all ? failures : failures.slice(0, 6);
  const headline = state === "running" ? "Self-check running in the background. Neyvia works normally meanwhile."
    : state === "passed" ? `Self-check passed${check.complete ? "" : " (some procedures need real runtimes and are not covered)"}.`
    : state === "failed" ? `Self-check found ${check.failureCount ?? failures.length} failing claim${(check.failureCount ?? failures.length) === 1 ? "" : "s"}. Neyvia still works.`
    : "Self-check could not finish. Neyvia still works.";
  return (
    <section className="nx-rt-block" aria-label="Readiness self-check" data-self-check={state}>
      <h4><StatusDot tone={tone} /> Readiness</h4>
      <p className="nx-rt-muted">{headline}</p>
      {state === "error" && check.error ? <p className="nx-rt-reason"><Icon as={TriangleAlert} size={13} />{check.error}</p> : null}
      {failures.length ? (
        <>
          <ul className="nx-rt-caps nx-rt-failures">
            {shownFailures.map(item => <li key={item.claim} title={item.error}><StatusDot tone="red" /><span>{item.claim}: {item.error}</span></li>)}
          </ul>
          {failures.length > 6 ? <button type="button" className="nx-rt-more" onClick={() => setAll(value => !value)}>{all ? "Show fewer" : `Show all ${failures.length}`}</button> : null}
        </>
      ) : null}
    </section>
  );
}

export function NxRuntime() {
  const [catalog, setCatalog] = useState(() => (lastCatalog ? { status: "ready", data: lastCatalog } : { status: "loading" }));
  const [matrix, setMatrix] = useState(() => (lastMatrix ? { status: "ready", data: lastMatrix } : { status: "loading" }));
  const [open, setOpen] = useState(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!version && lastCatalog && lastMatrix) return undefined;
    let live = true;
    setCatalog(current => ({ ...current, status: "loading" }));
    setMatrix(current => ({ ...current, status: "loading" }));
    callNx("get_harness_catalog_command", {})
      .then(data => { lastCatalog = data; if (live) setCatalog({ status: "ready", data }); })
      .catch(error => { if (live) setCatalog(current => ({ ...current, status: "error", error: error.message })); });
    runtimeApi()
      .then(data => { lastMatrix = data; if (live) setMatrix({ status: "ready", data }); })
      .catch(error => { if (live) setMatrix(current => ({ ...current, status: "error", error: error.message })); });
    return () => { live = false; };
  }, [version]);

  const selfCheckState = matrix.data?.selfCheck?.state;
  useEffect(() => {
    if (selfCheckState !== "running") return undefined;
    const timer = setInterval(() => runtimeApi().then(data => { lastMatrix = data; setMatrix({ status: "ready", data }); }).catch(() => {}), 30000);
    return () => clearInterval(timer);
  }, [selfCheckState]);
  const rows = mergeRuntimes(catalog.data, matrix.data);
  const busy = catalog.status === "loading" || matrix.status === "loading";
  useEffect(() => { if (!busy && rows.length) publish(runtimeSummary(rows)); }, [busy, rows.length, catalog.data, matrix.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const onSaved = useCallback(policies => setMatrix(current => {
    lastMatrix = { ...current.data, policies };
    return { ...current, data: lastMatrix };
  }), []);
  const summary = runtimeSummary(rows);
  const shown = rows.filter(row => !row.securityOnly);
  const security = rows.filter(row => row.securityOnly);

  return (
    <div className="nx-rt nx-scroll">
      <NxConnections />
      <header className="nx-rt-head nx-rt-head-detail">
        <div>
          <h3>Runtimes in detail</h3>
          <p>{busy && !rows.length ? "Checking what's on this PC…" : `${summary.ready} ready to use, ${summary.installed} found on this PC, ${summary.total} known.`}
            {catalog.status === "loading" ? " Checking versions and sign-in takes about 20 seconds." : ""}</p>
        </div>
        <span className="nx-head-spacer" />
        {busy && rows.length ? <Spinner size={14} /> : null}
        <IconButton icon={RefreshCw} label="Check again" disabled={busy} onClick={() => setVersion(value => value + 1)} />
      </header>
      <SelfCheck check={matrix.data?.selfCheck} />
      {catalog.status === "error" ? <p className="nx-rt-reason"><Icon as={TriangleAlert} size={13} />Program check failed: {catalog.error}</p> : null}
      {matrix.status === "error" ? <p className="nx-rt-reason"><Icon as={TriangleAlert} size={13} />Connection check failed: {matrix.error}</p> : null}
      {rows.length ? (
        <>
          <div className="nx-rt-cols" aria-hidden="true">
            <span /><span>Runtime</span><span>On this PC</span><span>Version</span><span>How Neyvia uses it</span><span>Starts chats</span><span>Status</span>
          </div>
          <ul className="nx-rt-list">
            {shown.map(row => <Row key={row.id} row={row} open={open === row.id} onToggle={() => setOpen(open === row.id ? null : row.id)} onSaved={onSaved} />)}
          </ul>
          {security.length ? (
            <>
              <h4 className="nx-rt-group">Security testing only</h4>
              <ul className="nx-rt-list">
                {security.map(row => <Row key={row.id} row={row} open={open === row.id} onToggle={() => setOpen(open === row.id ? null : row.id)} onSaved={onSaved} />)}
              </ul>
            </>
          ) : null}
        </>
      ) : busy ? (
        <ul className="nx-rt-skel" aria-busy="true" aria-label="Checking what is on this PC">
          {[0, 1, 2, 3, 4, 5, 6].map(index => <li key={index}><i /><span /><span /><span /></li>)}
        </ul>
      ) : null}
    </div>
  );
}
