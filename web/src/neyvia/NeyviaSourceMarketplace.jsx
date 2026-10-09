import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppWindow, ArrowLeft, Aperture, Check, Clapperboard, Code2, ExternalLink, Frame, GraduationCap, Layers, MessageCircle, NotebookPen,
  PackageOpen, Plus, Puzzle, RefreshCw, Search, Trash2, TriangleAlert, Video,
} from "lucide-react";

import { createNeyviaClient } from "../../../packages/neyvia-sdk/index.js";
import { Button, Icon, Segmented, StatusDot } from "./next/nxPrimitives.jsx";
import { ConfirmInPlace, CopyButton, EmptyState, useCalmLoading } from "./next/details/nxDetails.jsx";
import { NxFolderPicker } from "./next/NxFolderPicker.jsx";
import { ProviderMark } from "./next/ProviderMark.jsx";
import { marketplaceCompatibility } from "./neyviaMarketplaceModel.js";
import {
  contractRows, filterItems, glyphKey, kindLabel, monogram, permissionRows, plainError, readManual, shortSource, shortVersion,
  sourceLabel, storeState, when,
} from "./neyviaSourceStoreModel.js";
import "./neyviaSourceStore.css";

const sdk = createNeyviaClient();
const call = (operation, args = {}) => sdk.command(`source_marketplace_${operation}_command`, args);

const GLYPHS = {
  layers: Layers, clapperboard: Clapperboard, video: Video, frame: Frame, aperture: Aperture, message: MessageCircle,
  study: GraduationCap, notes: NotebookPen, code: Code2, app: AppWindow, mod: Puzzle,
};

/** The package's own icon when its manifest has one; otherwise a drawn glyph on a tinted tile (never a letter pair). */
function StoreIcon({ item, size = "md" }) {
  if (item.icon) return <span className={`nx-store-icon is-${size}`} aria-hidden="true"><img alt="" src={item.icon} /></span>;
  const mark = monogram(item.name, item.id);
  const Glyph = GLYPHS[glyphKey(item)] || Puzzle;
  return <span className={`nx-store-icon is-${size} is-glyph is-${mark.tone}`} aria-hidden="true"><Glyph strokeWidth={1.6} /></span>;
}

function StatePill({ state }) {
  if (!state.label) return null;
  return <span className={`nx-store-pill is-${state.id}`}><StatusDot tone={state.tone} />{state.label}</span>;
}

/** The enable switch names its ON state; it is disabled while the item is changed on disk. */
function EnableSwitch({ item, busy, onToggle, showLabel = false, pending = null }) {
  // While the backend answers, the switch already shows where it is going.
  const on = pending ? pending.on : item.state === "active";
  return (
    <label className={`nx-store-switch${showLabel ? " has-label" : ""}`}>
      {showLabel ? <span>{pending ? (on ? "Turning on…" : "Turning off…") : on ? "Enabled" : "Off"}</span> : null}
      <span className={`nx-store-switch-track${on ? " is-on" : ""}${pending ? " is-pending" : ""}`}>
        <input type="checkbox" role="switch" aria-label={`${item.name} enabled`} checked={on} aria-busy={pending ? true : undefined}
          disabled={busy || item.state === "integrity-blocked"} onChange={event => onToggle(item, event.target.checked)} />
      </span>
    </label>
  );
}

function StoreCard({ item, state, busy, pending, onOpen, onToggle, onInstall }) {
  const compatibility = marketplaceCompatibility(item.compat);
  return (
    <li className={`nx-store-card is-${state.id}`} data-store-item={item.id} data-store-state={state.id}>
      <button type="button" className="nx-store-card-main" onClick={() => onOpen(item)} aria-label={`${item.name}, ${kindLabel(item.kind)}${state.label ? `, ${state.label}` : ""}. Show details`}>
        <StoreIcon item={item} />
        <span className="nx-store-card-title">
          <strong>{item.name}</strong>
          <span className="nx-store-meta">
            {kindLabel(item.kind)}{item.version ? <> · <code>{shortVersion(item.version)}</code></> : null} · {sourceLabel(item)}
          </span>
        </span>
      </button>
      <p className="nx-store-card-summary">{item.summary || "No description in its manifest."}</p>
      <p className="nx-store-meta" data-marketplace-compat={compatibility.status} title={compatibility.detail}>{compatibility.label}</p>
      <footer className="nx-store-card-foot">
        {state.label ? <StatePill state={state} /> : <span className="nx-store-meta">Not installed</span>}
        {item.state === "available"
          ? <Button size="sm" variant="outline" icon={Plus} loading={busy === `install:${item.id}`} disabled={Boolean(busy)} onClick={() => onInstall(item)}>Install</Button>
          : <EnableSwitch item={item} busy={Boolean(busy)} onToggle={onToggle} pending={pending?.id === item.id ? pending : null} />}
      </footer>
    </li>
  );
}

function SkeletonGrid() {
  return (
    <ul className="nx-store-grid is-loading" aria-hidden="true">
      {[0, 1, 2].map(index => <li key={index} className="nx-store-card is-skeleton"><span /><span /><span /></li>)}
    </ul>
  );
}

function AddFromSource({ busy, onInstall, onCancel }) {
  const [mode, setMode] = useState("folder");
  const [folder, setFolder] = useState("");
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("");
  const source = mode === "folder" ? folder.trim() : url.trim();
  return (
    <form className="nx-store-add" aria-label="Add from source" data-store-add="true"
      onSubmit={event => { event.preventDefault(); if (source) onInstall({ source, ref: mode === "github" ? ref.trim() || "HEAD" : "HEAD" }); }}>
      <div className="nx-store-add-head">
        <div><strong>Add from source</strong><p>It installs turned off. Look it over, then turn it on.</p></div>
        <Segmented size="sm" label="Source type" value={mode} onChange={setMode}
          options={[{ value: "folder", label: "Folder" }, { value: "github", label: "GitHub" }]} />
      </div>
      {mode === "folder" ? (
        <div className="nx-store-add-fields">
          <NxFolderPicker value={folder ? { path: folder } : null} onChange={choice => setFolder(choice?.path || "")} recent={[]}
            placeholder="Choose a folder" hint="With neyvia.app.json or neyvia.module.json" />
          <label className="nx-store-field">
            <span>Or paste its path</span>
            <input className="nx-input" aria-label="App or mod source" placeholder="C:\Users\you\Projects\my-app" value={folder}
              onChange={event => setFolder(event.target.value)} spellCheck={false} />
          </label>
        </div>
      ) : (
        <div className="nx-store-add-fields is-github">
          <label className="nx-store-field">
            <span>Repository</span>
            <input className="nx-input" aria-label="App or mod source" placeholder="https://github.com/owner/repo" value={url}
              onChange={event => setUrl(event.target.value)} spellCheck={false} inputMode="url" />
          </label>
          <label className="nx-store-field is-ref">
            <span>Branch or tag</span>
            <input className="nx-input" aria-label="Source revision" placeholder="Default branch" value={ref}
              onChange={event => setRef(event.target.value)} spellCheck={false} />
          </label>
        </div>
      )}
      <div className="nx-store-add-actions">
        <Button size="sm" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" type="submit" icon={Plus} loading={busy === "install"} disabled={!source || Boolean(busy)}>Install</Button>
      </div>
    </form>
  );
}

function Checklist({ rows, icon = Check }) {
  return (
    <ul className="nx-store-checklist">
      {rows.map(row => (
        <li key={row.id}><Icon as={icon} size={14} /><span>{row.text}{row.detail ? <code>{row.detail}</code> : null}</span></li>
      ))}
    </ul>
  );
}

function StoreDetail({ item, state, read, readError, busy, pending, onBack, onToggle, onUpdate, onRemove, onInstall, onOpenApp }) {
  const compatibility = marketplaceCompatibility(item.compat);
  const [showManual, setShowManual] = useState(false);
  const manual = useMemo(() => readManual(read?.manual), [read?.manual]);
  const declared = item.actions?.length ? item.actions.map(action => ({ id: action.name, text: action.description || action.name, detail: action.name }))
    : manual.actions.map(action => ({ id: action.name, text: action.text, detail: action.name }));
  const installed = item.state !== "available";
  const versions = read?.versions || [];
  const repository = item.sourceRepository;
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, [item.id]);
  return (
    <article className="nx-store-detail" aria-labelledby="nx-store-detail-title" data-store-detail={item.id}>
      <Button size="sm" icon={ArrowLeft} className="nx-store-back" onClick={onBack}>All apps and mods</Button>
      <header className="nx-store-detail-head">
        <StoreIcon item={item} size="lg" />
        <div>
          <div className="nx-store-detail-title">
            <h3 id="nx-store-detail-title" tabIndex={-1} ref={heading}>{item.name}</h3>
            <StatePill state={state} />
          </div>
          <p className="nx-store-meta">{kindLabel(item.kind)} · {sourceLabel(item)}{item.version ? <> · version <code>{shortVersion(item.version)}</code></> : null}</p>
          <p className="nx-store-detail-summary">{item.summary || "No description in its manifest."}</p>
          <p className="nx-store-meta" data-marketplace-compat={compatibility.status} title={compatibility.detail}>{compatibility.label}</p>
          {item.upstream?.repository ? <p className="nx-store-meta" data-store-upstream="true">Built on <a href={item.upstream.repository} target="_blank" rel="noreferrer">{shortSource(item.upstream.repository)}</a>{item.upstream.license ? <> · {item.upstream.license}</> : null}</p> : null}
        </div>
      </header>

      <div className="nx-store-detail-actions" data-store-actions="true">
        {installed ? (
          <>
            <EnableSwitch item={item} busy={Boolean(busy)} onToggle={onToggle} showLabel pending={pending?.id === item.id ? pending : null} />
            {item.kind === "app" && item.state === "active"
              ? <Button size="sm" variant="primary" icon={ExternalLink} onClick={() => onOpenApp(item)}>Open app</Button> : null}
            <Button size="sm" variant={state.id === "update" || state.id === "blocked" ? "outline" : "ghost"} icon={RefreshCw}
              loading={busy === `update:${item.id}`} disabled={Boolean(busy)} onClick={() => onUpdate(item)}>Update</Button>
            <ConfirmInPlace question={item.state === "active" ? `Turn off and remove ${item.name}?` : `Remove ${item.name}?`}
              confirmLabel="Remove" doneText={`${item.name} removed`} onConfirm={() => onRemove(item)}>
              {ask => <Button size="sm" icon={Trash2} className="nx-store-remove" disabled={Boolean(busy)} onClick={ask}>Remove</Button>}
            </ConfirmInPlace>
          </>
        ) : (
          <Button size="sm" variant="primary" icon={Plus} loading={busy === `install:${item.id}`} disabled={Boolean(busy)} onClick={() => onInstall(item)}>Install</Button>
        )}
      </div>
      {installed && item.state === "disabled" ? <p className="nx-store-hint">Off. Read what it does and what it asks for, then turn it on.</p> : null}
      {state.id === "blocked" ? <p className="nx-store-hint is-warn"><Icon as={TriangleAlert} size={14} />Its installed files changed on disk, so it stays off. Update takes a fresh copy from its source.</p> : null}

      <section aria-labelledby="nx-store-can">
        <h4 id="nx-store-can">What it can do</h4>
        {declared.length ? <Checklist rows={declared} icon={Check} /> : <p className="nx-store-quiet">{read ? "Its manual names no actions." : readError || "Reading its manual…"}</p>}
      </section>

      <section aria-labelledby="nx-store-asks">
        <h4 id="nx-store-asks">What it asks for</h4>
        <Checklist rows={permissionRows(item)} />
      </section>

      <section aria-labelledby="nx-store-promises">
        <h4 id="nx-store-promises">What it promises</h4>
        {contractRows(read?.contracts || item.contracts).length
          ? <Checklist rows={contractRows(read?.contracts || item.contracts)} />
          : <p className="nx-store-quiet">It declares no contracts.</p>}
        {manual.limits.length ? (
          <>
            <h5>Limits it states</h5>
            <ul className="nx-store-limits">{manual.limits.map(limit => <li key={limit}>{limit}</li>)}</ul>
          </>
        ) : null}
      </section>

      {installed ? (
        <section aria-labelledby="nx-store-versions">
          <h4 id="nx-store-versions">Versions</h4>
          {versions.length ? (
            <ol className="nx-store-versions">
              {versions.map(row => (
                <li key={row.version}>
                  <code>{shortVersion(row.version)}</code>
                  <span>{row.current ? "Current" : row.previous ? "Previous" : "Kept"}</span>
                  <time dateTime={row.installedAt}>{when(row.installedAt)}</time>
                </li>
              ))}
            </ol>
          ) : <p className="nx-store-quiet">{read ? "No saved versions." : "Reading…"}</p>}
        </section>
      ) : null}

      <section aria-labelledby="nx-store-source">
        <h4 id="nx-store-source">Source</h4>
        <div className="nx-store-source-row">
          {item.sourceKind === "github"
            ? <a className="nx-link" href={item.source} target="_blank" rel="noreferrer noopener"><ProviderMark id="github" size={13} />{shortSource(item.source)}</a>
            : <code title={item.source}>{item.source}</code>}
          {item.ref && item.ref !== "HEAD" ? <span className="nx-store-meta">at <code>{item.ref}</code></span> : null}
          <CopyButton text={item.source} label="Copy source" />
        </div>
        {repository && item.sourceKind !== "github"
          ? <a className="nx-link nx-store-repo" href={repository} target="_blank" rel="noreferrer noopener"><ProviderMark id="github" size={13} />{shortSource(repository)}</a> : null}
      </section>

      {read || readError ? (
        <section className="nx-store-manual">
          <Button size="sm" variant="ghost" aria-expanded={showManual} aria-controls="nx-store-manual-text"
            onClick={() => setShowManual(open => !open)} disabled={!read}>{showManual ? "Hide manual" : "Show manual"}</Button>
          {readError ? <p className="nx-store-quiet">{readError}</p> : null}
          {showManual && read ? <pre id="nx-store-manual-text" className="nx-store-manual-text nx-scroll">{read.manual}</pre> : null}
        </section>
      ) : null}
    </article>
  );
}

function AppView({ item, onBack }) {
  return (
    <div className="nx-store-app" data-store-app={item.id}>
      <div className="nx-store-app-bar">
        <Button size="sm" icon={ArrowLeft} onClick={onBack}>Store</Button>
        <StoreIcon item={item} size="sm" />
        <strong>{item.name}</strong>
      </div>
      <iframe title={item.name} src={`/api/application/${encodeURIComponent(item.id)}/`} className="nx-store-app-frame" />
    </div>
  );
}

export function NeyviaSourceMarketplace({ refreshKey = 0 }) {
  const [catalog, setCatalog] = useState({ status: "loading", items: [], available: [] });
  const [updates, setUpdates] = useState({});
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [running, setRunning] = useState(null);
  const [reads, setReads] = useState({});
  const [busy, setBusy] = useState("");
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState("");
  const showLoading = useCalmLoading(catalog.status === "loading");

  const refresh = useCallback(async () => {
    try {
      const result = await call("list");
      setCatalog({ status: "ready", items: result.items || [], available: result.available || [] });
      call("updates").then(next => setUpdates(next.updates || {})).catch(() => setUpdates({}));
    } catch (failure) {
      setCatalog(current => ({ ...current, status: current.items.length ? "ready" : "error" }));
      setError(plainError(failure));
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh, refreshKey]);

  const all = useMemo(() => [
    ...[...catalog.items].sort((a, b) => Number(b.state === "active") - Number(a.state === "active") || a.name.localeCompare(b.name)),
    ...catalog.available,
  ], [catalog]);
  const shown = useMemo(() => filterItems(all, { filter, query }), [all, filter, query]);
  const counts = useMemo(() => ({
    all: all.length, app: all.filter(item => item.kind === "app").length, mod: all.filter(item => item.kind === "mod").length,
    installed: catalog.items.length,
  }), [all, catalog.items.length]);
  const selected = all.find(item => item.id === selectedId) || null;

  const loadRead = useCallback(async id => {
    try {
      const result = await call("read", { id });
      setReads(current => ({ ...current, [id]: { data: result } }));
    } catch (failure) {
      setReads(current => ({ ...current, [id]: { error: plainError(failure).text } }));
    }
  }, []);
  useEffect(() => {
    if (selected && !reads[selected.id]) void loadRead(selected.id);
  }, [selected, reads, loadRead]);

  const run = async (key, intent, work) => {
    setBusy(key); setError(null); setNotice("");
    try {
      const message = await work();
      await refresh();
      if (message) setNotice(message);
    } catch (failure) {
      setError(plainError(failure, intent));
      await refresh();
    } finally {
      setBusy("");
    }
  };

  const install = ({ source, ref }, itemId = "") => run(itemId ? `install:${itemId}` : "install", "install", async () => {
    const result = await call("install", { source, ref });
    setAdding(false);
    setSelectedId(result.item.id);
    setReads(current => { const next = { ...current }; delete next[result.item.id]; return next; });
    return `${result.item.name} is installed and off. Turn it on when you're ready.`;
  });
  const toggle = async (item, enabled) => {
    setPending({ id: item.id, on: enabled });
    try {
      await run(`set:${item.id}`, enabled ? "enable" : "disable", async () => {
        const result = await call("set", { id: item.id, enabled });
        return result.item.state === "active" ? `${result.item.name} is on.` : `${result.item.name} is off.`;
      });
    } finally {
      setPending(null);
    }
  };
  const update = item => run(`update:${item.id}`, "update", async () => {
    const before = item.version;
    const result = await call("update", { id: item.id });
    setReads(current => { const next = { ...current }; delete next[item.id]; return next; });
    return result.item.version === before ? `${result.item.name} is already up to date.` : `${result.item.name} updated to ${shortVersion(result.item.version)}.`;
  });
  const remove = item => run(`remove:${item.id}`, "remove", async () => {
    if (item.state === "active") await call("set", { id: item.id, enabled: false });
    const result = await call("remove", { id: item.id });
    setSelectedId("");
    setReads(current => { const next = { ...current }; delete next[item.id]; return next; });
    return `${result.item.name} removed. Its saved copies were moved aside, not deleted.`;
  });

  if (running) {
    return (
      <section id="neyvia-marketplace-sources" role="tabpanel" aria-labelledby="neyvia-marketplace-sources-tab" className="nx-store">
        <AppView item={running} onBack={() => setRunning(null)} />
      </section>
    );
  }

  const read = selected ? reads[selected.id] : null;
  return (
    <section id="neyvia-marketplace-sources" role="tabpanel" aria-labelledby="neyvia-marketplace-sources-tab"
      className={`nx-store${selected ? " has-detail" : ""}`} data-store-status={catalog.status}>
      <div className="nx-store-bar">
        <label className="nx-store-search">
          <Icon as={Search} size={14} />
          <input type="search" aria-label="Search apps and mods" placeholder="Search apps and mods" value={query} onChange={event => setQuery(event.target.value)} />
        </label>
        <Segmented size="sm" label="Show" value={filter} onChange={setFilter} options={[
          { value: "all", label: "All", count: counts.all || undefined },
          { value: "app", label: "Apps", count: counts.app || undefined },
          { value: "mod", label: "Mods", count: counts.mod || undefined },
          { value: "installed", label: "Installed", count: counts.installed || undefined },
        ]} />
        <Button size="sm" variant={adding ? "ghost" : "outline"} icon={Plus} aria-expanded={adding} onClick={() => setAdding(open => !open)}>Add from source</Button>
      </div>

      {adding ? <AddFromSource busy={busy} onInstall={value => void install(value)} onCancel={() => setAdding(false)} /> : null}

      <div className="nx-store-messages" aria-live="polite">
        {error ? (
          <div className="nx-store-error" role="alert">
            <Icon as={TriangleAlert} size={14} /><span>{error.text}</span>
            {error.raw && error.raw !== error.text ? <CopyButton text={error.raw} label="Copy details" size="xs" /> : null}
          </div>
        ) : null}
        {notice ? <p className="nx-store-notice" role="status"><Icon as={Check} size={14} />{notice}</p> : null}
      </div>

      <div className="nx-store-body">
        <div className="nx-store-browse">
          {catalog.status === "loading" ? (showLoading ? <SkeletonGrid /> : null)
            : catalog.status === "error" && !all.length ? (
              <EmptyState icon={TriangleAlert} title="The store couldn't load" hint={error?.text || "Neyvia's backend didn't answer."}
                action={{ label: "Try again", icon: RefreshCw, onClick: () => { setCatalog(current => ({ ...current, status: "loading" })); void refresh(); } }} />
            ) : !all.length ? (
              <EmptyState icon={PackageOpen} title="No apps or mods yet" hint="Add one from a folder on this PC or a GitHub repository."
                action={adding ? undefined : { label: "Add from source", icon: Plus, onClick: () => setAdding(true) }} />
            ) : !shown.length ? (
              <EmptyState tone="filtered" icon={Search} title={query ? `Nothing matches “${query.trim()}”` : "Nothing here yet"}
                hint={filter === "installed" ? "Install one to see it here." : "Try another word or filter."}
                action={{ label: "Show all", onClick: () => { setQuery(""); setFilter("all"); } }} />
            ) : (
              <ul className="nx-store-grid" aria-label="Apps and mods">
                {shown.map(item => (
                  <StoreCard key={item.id} item={item} state={storeState(item, updates)} busy={busy} pending={pending}
                    onOpen={next => setSelectedId(next.id)} onToggle={(next, enabled) => void toggle(next, enabled)}
                    onInstall={next => void install({ source: next.source, ref: "HEAD" }, next.id)} />
                ))}
              </ul>
            )}
        </div>
        {selected ? (
          <StoreDetail item={selected} state={storeState(selected, updates)} read={read?.data} readError={read?.error} busy={busy} pending={pending}
            onBack={() => setSelectedId("")} onToggle={(next, enabled) => void toggle(next, enabled)} onUpdate={next => void update(next)}
            onRemove={next => void remove(next)} onInstall={next => void install({ source: next.source, ref: "HEAD" }, next.id)}
            onOpenApp={setRunning} />
        ) : null}
      </div>
    </section>
  );
}
