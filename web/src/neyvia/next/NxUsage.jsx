import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Gauge, RefreshCw, Sparkles } from "lucide-react";

import { backendBase } from "./nxApi.js";
import { os } from "./nxOsStore.js";
import { limitPercent, limitTone } from "./nxDashboardModel.js";
import { Button, Icon, IconButton, Segmented, Spinner, StatusDot } from "./nxPrimitives.jsx";
import {
  RANGES, ageText, agentName, appName, billingLabel, chartModel, dayLabel, fmtPercent, fmtTokens, fmtUsd, headline, partsText, planGroups, resetText, sourceName,
} from "./nxUsageModel.js";
import "./nxUsage.css";

// The Usage pane (pane.show {kind: "usage"}; Settings, the Agents popover header, the launcher).
// One read-only endpoint, GET /api/ui/usage?range=: plan windows as the apps last reported them, tokens by day,
// agent and model from the records the apps already keep, and an estimated price only for API-key traffic.

function base() {
  const source = globalThis.window?.__NEYVIA_UI_SOURCE__;
  return backendBase() || (typeof source === "string" && source.startsWith("http") ? source : "");
}

async function usageApi(range) {
  const response = await fetch(`${base()}/api/ui/usage?range=${encodeURIComponent(range)}`, { credentials: "include" });
  const result = await response.json().catch(() => ({}));
  if (!response.ok || result?.ok === false) throw new Error(result?.error || `Usage could not be read (HTTP ${response.status})`);
  return result?.data ?? result;
}

const lastReading = {}; // per range, so reopening the pane is instant
const SCAN_POLL_MS = 3000;
const IDLE_POLL_MS = 60000;

function useUsage(range) {
  const [data, setData] = useState(() => lastReading[range] || null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const next = await usageApi(range);
      lastReading[range] = next;
      if (alive.current) { setData(next); setError(""); }
    } catch (failure) {
      if (alive.current) setError(failure?.message || "Usage could not be read.");
    } finally {
      if (alive.current) setBusy(false);
    }
  }, [range]);
  useEffect(() => { alive.current = true; setData(lastReading[range] || null); void load(); return () => { alive.current = false; }; }, [range, load]);
  const scanning = Boolean(data?.scan?.active);
  useEffect(() => {
    const timer = setInterval(() => { if (!globalThis.document?.hidden) void load(); }, scanning ? SCAN_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(timer);
  }, [scanning, load]);
  return { data, error, busy, reload: load };
}

function PlanBar({ row }) {
  const percent = limitPercent(row);
  const tone = limitTone(row);
  const width = percent == null ? 0 : Math.max(0, Math.min(100, percent));
  return (
    <li className={`nx-us-plan is-${tone}`}>
      <div className="nx-us-plan-top">
        <span className="nx-us-plan-label">{row.label || row.window}</span>
        <span className="nx-us-plan-value">{percent == null ? "Not reported" : <><b>{Math.round(percent)}%</b> of this window used</>}</span>
      </div>
      <div className="nx-us-bar" role="progressbar" aria-label={`${row.label || row.window} window used`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent == null ? undefined : Math.round(percent)}>
        <i style={{ width: `${width}%` }} />
      </div>
      <div className="nx-us-plan-foot">
        <span>{row.resetsAt ? (row.resetPassed ? `Reset ${resetText(row.resetsAt)}, after this reading` : `Resets ${resetText(row.resetsAt)}`) : "Reset time not reported"}</span>
        <span>{row.stale ? "Last known · " : ""}read {ageText(row.at) || "at an unknown time"} from {sourceName(row.source)}</span>
      </div>
    </li>
  );
}

function PlanCard({ group }) {
  const { app, rows, provider } = group;
  const note = provider?.error;
  return (
    <section className="nx-us-card nx-us-plancard" aria-label={`${appName(app)} plan windows`}>
      <header><strong>{appName(app)}</strong>{rows.length ? <StatusDot tone={rows.some(r => !r.stale) ? "green" : "idle"} /> : null}</header>
      {rows.length ? <ul className="nx-us-plans">{rows.map(row => <PlanBar key={`${row.app}-${row.window}`} row={row} />)}</ul> : (
        <div className="nx-us-empty">
          <p>{app === "opencode" ? "OpenCode does not report plan windows, only session statistics." : `No ${appName(app)} plan window has been read yet.`}</p>
          {note ? <small>{note}</small> : null}
          {app === "opencode" ? null : <Button size="sm" variant="ghost" onClick={() => os.showPane("runtime", "")}>Connect in Runtimes</Button>}
        </div>
      )}
    </section>
  );
}

function Tile({ label, value, unit, note, tone }) {
  return (
    <div className={`nx-us-tile${tone ? ` is-${tone}` : ""}`}>
      <small>{label}</small>
      <strong>{value}{unit ? <em>{unit}</em> : null}</strong>
      <span>{note}</span>
    </div>
  );
}

function Chart({ byDay, mode }) {
  const model = useMemo(() => chartModel(byDay, mode), [byDay, mode]);
  if (model.empty) return <div className="nx-us-empty is-chart"><p>No tokens recorded in this range.</p><small>Chats with Claude Code, Codex or the Neyvia agent on this PC appear here.</small></div>;
  const { columns, scale, series } = model;
  return (
    <figure className="nx-us-chart" aria-label="Tokens per day, stacked by agent">
      <div className="nx-us-plot">
        <div className="nx-us-yaxis" aria-hidden="true">
          {[...scale.ticks].reverse().map(tick => <span key={tick}>{fmtTokens(tick)}</span>)}
        </div>
        <div className="nx-us-cols" style={{ "--nx-us-n": columns.length }}>
          <div className="nx-us-grid" aria-hidden="true"><i /><i /><i /></div>
          {columns.map((col, index) => {
            const text = `${col.day}: ${fmtTokens(col.total)} tokens${col.parts.filter(p => p.value).map(p => ` · ${p.label} ${fmtTokens(p.value)}`).join("")}`;
            return (
              <div key={col.day} className="nx-us-col" title={text} aria-label={text} role="img">
                <div className="nx-us-stack">
                  {col.parts.filter(p => p.value > 0).map(p => <i key={p.name} style={{ height: `${(p.value / scale.top) * 100}%`, background: p.color }} />)}
                </div>
                <span className="nx-us-x">{dayLabel(col.day, index, columns.length)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <figcaption>
        <ul className="nx-us-legend">{series.map(s => <li key={s.name}><i style={{ background: s.color }} />{s.label}</li>)}</ul>
        <span>Tokens per day, local time</span>
      </figcaption>
    </figure>
  );
}

function Table({ rows }) {
  if (!rows.length) return <div className="nx-us-empty is-chart"><p>No agent or model has run in this range.</p></div>;
  return (
    <div className="nx-us-table" role="table" aria-label="Tokens by agent and model">
      <div className="nx-us-tr nx-us-th" role="row">
        <span role="columnheader">Agent · model</span><span role="columnheader">Billing</span>
        <span role="columnheader" className="num">Input (tokens)</span><span role="columnheader" className="num">Cached share</span>
        <span role="columnheader" className="num">Output (tokens)</span><span role="columnheader" className="num">API-equivalent (USD)</span>
        <span role="columnheader" className="num">Billed to your key (USD)</span>
      </div>
      {rows.map(row => (
        <div className="nx-us-tr" role="row" key={`${row.agent}-${row.provider}-${row.model}-${row.billing}`}>
          <span role="cell" className="nx-us-who"><b>{agentName(row.agent)}</b><small title={row.model}>{row.model}</small></span>
          <span role="cell"><em className={`nx-us-pill is-${row.billing}`}>{billingLabel(row.billing)}</em></span>
          <span role="cell" className="num" data-label="Input"><b>{fmtTokens(row.input)}</b></span>
          <span role="cell" className="num" data-label="Cached">{fmtPercent(row.cacheShare)}</span>
          <span role="cell" className="num" data-label="Output">{fmtTokens(row.output)}</span>
          <span role="cell" className="num" data-label="API-equivalent" title={partsText(row.apiEquivParts)}>
            {row.apiEquivUsd == null ? <span className="nx-us-muted" title="No public list price on file for this model">no price on file</span> : <b>{fmtUsd(row.apiEquivUsd)}</b>}
            {row.apiEquivUsd != null && row.billing !== "api" ? <small className="nx-us-sub">not billed to you</small> : null}
          </span>
          <span role="cell" className="num" data-label="Billed">
            {row.billing === "api" ? (row.billedUsd == null ? <span className="nx-us-muted">no price on file</span> : <b>{fmtUsd(row.billedUsd)}</b>) : <span className="nx-us-muted">&mdash;</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

export function NxUsage() {
  const [range, setRange] = useState("week");
  const [mode, setMode] = useState("fresh");
  const { data, error, busy, reload } = useUsage(range);
  const groups = useMemo(() => planGroups(data?.plans, data?.providers), [data]);
  const head = useMemo(() => headline(data), [data]);
  const scan = data?.scan;
  const priced = head.pricedShare == null ? "" : ` · ${fmtPercent(head.pricedShare)} of tokens have a price on file`;
  return (
    <div className="nx-us">
      <header className="nx-us-head">
        <div>
          <h3>Usage</h3>
          <p>What your plans have used, how many tokens went where, and what it is worth at public API prices. Plan usage is never a bill.</p>
        </div>
        <div className="nx-us-tools">
          <Segmented size="sm" label="Time range" value={range} options={RANGES} onChange={setRange} />
          <IconButton size="sm" icon={RefreshCw} label="Refresh usage" loading={busy} onClick={reload} />
        </div>
      </header>
      {error ? <p className="nx-notice is-error" role="alert">Usage could not be read: {error}</p> : null}
      {scan?.active ? <p className="nx-us-scan" role="status"><Spinner size={11} />Reading local chat records · {scan.done} of {scan.total} files. Numbers below fill in as this finishes.</p> : null}
      {!data && !error ? <p className="nx-us-scan" role="status"><Spinner size={11} />Reading usage…</p> : null}
      {data ? (
        <>
          <section aria-label="Plan windows">
            <h4 className="nx-us-h"><Icon as={Gauge} size={13} />Plan windows</h4>
            <div className="nx-us-plangrid">{groups.map(group => <PlanCard key={group.app} group={group} />)}</div>
          </section>
          <section aria-label="Totals" className="nx-us-tiles">
            <Tile label="New tokens" value={fmtTokens(head.fresh)} unit="tokens" note={`input not read from cache, plus output · last ${data.days} d`} />
            <Tile label="Output" value={fmtTokens(head.output)} unit="tokens" note="written by models" />
            <Tile label="Cache share" value={fmtPercent(head.cacheShare, 1)} note={`${fmtTokens(head.cached)} input tokens read from cache`} />
            <Tile label="API-equivalent value" value={head.equivalentUsd == null ? "—" : fmtUsd(head.equivalentUsd)} unit={head.equivalentUsd == null ? "" : "USD, estimate"} note={`all usage at public API list prices, not billed to you${priced}`} tone="equiv" />
            <Tile label="Billed to your keys" value={head.billedUsd == null ? "—" : fmtUsd(head.billedUsd)} unit={head.billedUsd == null ? "" : "USD, estimate"} note={head.apiRows ? `${head.apiRows} API-key ${head.apiRows === 1 ? "row" : "rows"}, at list price` : "No API-key traffic in this range"} tone={head.apiRows ? "api" : ""} />
          </section>
          <section aria-label="Tokens over time" className="nx-us-card">
            <header className="nx-us-sechead">
              <h4 className="nx-us-h">Tokens over time</h4>
              <Segmented size="sm" label="Count" value={mode} onChange={setMode} options={[{ value: "fresh", label: "New tokens" }, { value: "all", label: "With cache reads" }]} />
            </header>
            <Chart byDay={data.byDay} mode={mode} />
            {mode === "all" ? <p className="nx-us-hint">Cache reads re-send context already held by the provider, so they dwarf the real work.</p> : null}
          </section>
          <section aria-label="By agent and model" className="nx-us-card">
            <h4 className="nx-us-h">By agent and model</h4>
            <Table rows={data.rows || []} />
          </section>
          <p className="nx-us-saving">
            <Icon as={Sparkles} size={13} />
            {head.cacheShare == null ? "Nothing to compare yet." : `Cache served ${fmtPercent(head.cacheShare, 1)} of input tokens (${fmtTokens(head.cached)}).`}
            {data.savings?.apiEquivalentSavedUsd != null ? ` At API list prices that is worth about ${fmtUsd(data.savings.apiEquivalentSavedUsd)} less than sending it uncached (API-equivalent).` : ""}
            {data.savings?.billedSavedUsd != null ? ` On your API-key traffic it saved about ${fmtUsd(data.savings.billedSavedUsd)}.` : ""}
          </p>
          <footer className="nx-us-foot">
            <p>Tokens come from Claude Code transcripts, Codex session logs, OpenCode's local database and Neyvia agent turns on this PC, last {data.windowDays} days. Claude: one count per message id across files, thinking counted as output. Codex: one count per model request, matching each log's own running total. OpenCode: one count per assistant message, cache added back into input.</p>
            <p>Prices are public API list prices per million tokens, checked {data.cost?.pricesChecked || "—"}, with input, cache reads, cache writes and output priced separately. API-equivalent is what the same tokens would cost through API keys; it is an estimate, not an invoice, and plan usage is not billed to you.</p>
            {head.unpriced.length ? <p>No price on file for {head.unpriced.join(", ")}; they are left out of the totals, never guessed.</p> : null}
          </footer>
        </>
      ) : null}
    </div>
  );
}
