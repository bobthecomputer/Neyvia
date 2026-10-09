import { useState } from "react";
import { ChevronRight, FileCode2, RefreshCw, Search, Users } from "lucide-react";

import "./nxAwareness.css";
import { Button, Icon, IconButton, Spinner, StatusDot, ago } from "./nxPrimitives.jsx";
import { checkImpact, claimFiles, parsePaths, releaseClaim, shortPath, useWorkBoard } from "./nxAwareness.js";

// Awareness app (Lab). User side of neyvia.work.* and neyvia.impact: see who
// is changing which files right now, and what a change touches before it lands.

function Claim({ claim, onRelease, busy }) {
  const files = claim.files || [];
  return (
    <li className={`nx-aware-claim${claim.stale ? " is-stale" : ""}`}>
      <StatusDot tone={claim.stale ? "caution" : "green"} />
      <div className="nx-aware-claim-main">
        <div className="nx-aware-claim-head">
          <strong>{claim.agent}</strong>
          {claim.chat ? <span className="nx-aware-faint" title={claim.chat}>{claim.chat}</span> : null}
          <span className="nx-aware-faint" title={claim.since}>{claim.stale ? "idle for a while · " : ""}{ago(claim.since) || "now"}</span>
        </div>
        <p>{claim.intent}</p>
        <div className="nx-aware-chips">
          {files.slice(0, 4).map(path => <code key={path} title={path}>{shortPath(path)}</code>)}
          {files.length > 4 ? <span className="nx-aware-faint" title={files.slice(4).join("\n")}>+{files.length - 4} more</span> : null}
        </div>
      </div>
      <Button size="sm" variant={claim.stale ? "outline" : "ghost"} disabled={busy} onClick={() => onRelease(claim)}>Release</Button>
    </li>
  );
}

function Board({ board }) {
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const release = async claim => {
    setBusy(claim.id); setNote("");
    try { const result = await releaseClaim(claim.id); setNote(result?.message || "Released."); await board.refresh(); }
    catch (error) { setNote(error?.message || "Couldn't release it."); }
    finally { setBusy(""); }
  };
  const stale = board.claims.filter(claim => claim.stale).length;
  return (
    <section className="nx-aware-card" aria-labelledby="nx-aware-board">
      <header>
        <Icon as={Users} size={16} />
        <h2 id="nx-aware-board">Who's working on what</h2>
        <span className="nx-aware-faint">{board.claims.length ? `${board.claims.length} claim${board.claims.length > 1 ? "s" : ""}${stale ? ` · ${stale} idle` : ""}` : ""}</span>
        <span className="nx-aware-spacer" />
        <IconButton icon={RefreshCw} size="sm" label="Refresh" onClick={board.refresh} />
      </header>
      {board.status === "loading" ? <div className="nx-aware-empty"><Spinner size={14} /></div> : null}
      {board.status === "error" ? <p className="nx-aware-error">{board.error}</p> : null}
      {board.status === "ready" && !board.claims.length ? (
        <p className="nx-aware-empty">Nobody has claimed files right now. Agents claim files before they change them, so you'll see them here.</p>
      ) : null}
      {board.claims.length ? <ul className="nx-aware-claims">{board.claims.map(claim => <Claim key={claim.id} claim={claim} busy={busy === claim.id} onRelease={release} />)}</ul> : null}
      {note ? <p className="nx-aware-note" role="status">{note}</p> : null}
    </section>
  );
}

const ENDS = [["ui", "UI"], ["handler", "Backend"], ["bridge", "Desktop"], ["tauri", "Tauri"]];

function CommandRow({ row }) {
  return (
    <li className="nx-aware-cmd">
      <code>{row.command}</code>
      <span className="nx-aware-ends">
        {ENDS.map(([key, label]) => {
          const on = Array.isArray(row[key]) ? row[key].length > 0 : Boolean(row[key]);
          return on ? <span key={key} className="nx-aware-end" title={Array.isArray(row[key]) ? row[key].join("\n") : String(row[key] === true ? label : row[key])}>{label}</span> : null;
        })}
        {row.tests?.length ? <span className="nx-aware-end" title={row.tests.join("\n")}>{row.tests.length} test{row.tests.length > 1 ? "s" : ""}</span> : null}
        {(row.missing || []).map(item => <span key={item} className="nx-aware-end is-missing">{item}</span>)}
      </span>
    </li>
  );
}

function FileImpact({ file }) {
  const quiet = !file.commands?.length && !file.tools?.length && !file.dependents?.length && !file.tests?.length;
  return (
    <div className="nx-aware-file">
      <div className="nx-aware-file-head"><Icon as={FileCode2} size={14} /><strong title={file.path}>{file.path}</strong>{file.deleted ? <span className="nx-aware-end is-missing">deleted</span> : null}</div>
      {quiet ? <p className="nx-aware-faint">Nothing else names it.</p> : null}
      {file.commands?.length ? <ul className="nx-aware-cmds">{file.commands.map(row => <CommandRow key={row.command} row={row} />)}</ul> : null}
      {file.tools?.length ? (
        <ul className="nx-aware-cmds">{file.tools.map(tool => (
          <li key={tool.tool} className="nx-aware-cmd"><code>{tool.tool}</code><span className="nx-aware-ends">
            {tool.manuals.length ? <span className="nx-aware-end" title={tool.manuals.join("\n")}>Manual</span> : <span className="nx-aware-end is-missing">no manual</span>}
            {tool.tests.length ? <span className="nx-aware-end" title={tool.tests.join("\n")}>{tool.tests.length} test{tool.tests.length > 1 ? "s" : ""}</span> : null}
          </span></li>
        ))}</ul>
      ) : null}
      {file.dependents?.length ? <p className="nx-aware-also"><span>Used by</span> {file.dependents.slice(0, 6).map(path => <code key={path} title={path}>{shortPath(path)}</code>)}{file.dependents.length > 6 ? <span className="nx-aware-faint">+{file.dependents.length - 6}</span> : null}</p> : null}
      {file.tests?.length ? <p className="nx-aware-also"><span>Tests</span> {file.tests.slice(0, 6).map(path => <code key={path} title={path}>{shortPath(path)}</code>)}{file.tests.length > 6 ? <span className="nx-aware-faint">+{file.tests.length - 6}</span> : null}</p> : null}
    </div>
  );
}

function Gaps({ gaps }) {
  const [open, setOpen] = useState("");
  const rows = Object.entries(gaps || {});
  if (!rows.length) return null;
  return (
    <div className="nx-aware-gaps">
      <h3>Loose wiring in the app today</h3>
      <ul>
        {rows.map(([key, gap]) => (
          <li key={key}>
            <button type="button" className="nx-aware-gap" aria-expanded={open === key} disabled={!gap.count} onClick={() => setOpen(open === key ? "" : key)}>
              <Icon as={ChevronRight} size={13} className={open === key ? "is-open" : ""} />
              <span>{gap.help}</span>
              <span className={`nx-aware-count${gap.count ? " is-some" : ""}`}>{gap.count}</span>
            </button>
            {open === key ? <div className="nx-aware-chips is-list">{gap.items.map(item => <code key={item} title={(gap.where?.[item] || []).join("\n")}>{item}</code>)}{gap.count > gap.items.length ? <span className="nx-aware-faint">+{gap.count - gap.items.length} more</span> : null}</div> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Impact({ onClaimed }) {
  const [text, setText] = useState("");
  const [state, setState] = useState({ status: "idle" });
  const [claim, setClaim] = useState("");
  const paths = parsePaths(text);
  const claimThem = async () => {
    setClaim("busy");
    try { const result = await claimFiles(paths, "Paul is editing these by hand"); setClaim(result?.message || "Claimed."); onClaimed?.(); }
    catch (error) { setClaim(error?.message || "Couldn't claim them."); }
  };
  const run = async () => {
    setState({ status: "busy" });
    try { setState({ status: "ready", result: await checkImpact(paths) }); }
    catch (error) { setState({ status: "error", error: error?.message || "The check didn't finish." }); }
  };
  const result = state.result;
  return (
    <section className="nx-aware-card" aria-labelledby="nx-aware-impact">
      <header><Icon as={Search} size={16} /><h2 id="nx-aware-impact">What does a change touch?</h2></header>
      <textarea className="nx-aware-input" rows={3} value={text} onChange={event => setText(event.target.value)}
        placeholder={"One file per line, like src/app.js\nOr leave it empty to check what you haven't committed yet."}
        onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void run(); }} />
      <div className="nx-aware-actions">
        <Button variant="primary" disabled={state.status === "busy"} onClick={run}>{paths.length ? "Check these files" : "Check my changes"}</Button>
        {paths.length ? <Button variant="outline" disabled={claim === "busy"} onClick={claimThem} title="Agents will see that you are in these files">I'm editing these</Button> : null}
        {state.status === "busy" ? <Spinner size={14} /> : null}
        {result ? <span className="nx-aware-faint">{result.files.length} file{result.files.length === 1 ? "" : "s"} · {result.source === "git" ? "uncommitted changes" : "your list"} · {result.elapsedMs} ms</span> : null}
      </div>
      {claim && claim !== "busy" ? <p className="nx-aware-note" role="status">{claim}</p> : null}
      {state.status === "error" ? <p className="nx-aware-error">{state.error}</p> : null}
      {result && !result.files.length ? <p className="nx-aware-empty">{result.source === "git" ? "No uncommitted changes." : "No files given."}</p> : null}
      {result?.files.map(file => <FileImpact key={file.path} file={file} />)}
      {result ? <Gaps gaps={result.gaps} /> : null}
    </section>
  );
}

export function NxAwareness() {
  const board = useWorkBoard();
  return (
    <div className="nx-aware">
      <Board board={board} />
      <Impact onClaimed={board.refresh} />
    </div>
  );
}
