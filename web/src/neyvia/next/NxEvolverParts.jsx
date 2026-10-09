import { useEffect, useState } from "react";
import { ChevronRight, Copy, GitBranch, Lock, LockOpen } from "lucide-react";

import { callNx } from "./nxApi.js";
import { Icon, Spinner, StatusDot } from "./nxPrimitives.jsx";
import {
  diffLines, explainTrial, formatGain, formatValue, frontPoints, gateSteps, lineageTree, objectiveLabel, objectiveOrder,
  objectiveVerdict, operatorLabel, panelRows, percentChange, proposalFacts, seconds, shortHash, splitError, stageLabel, trialState, when,
} from "./nxEvolverModel.js";

// Pieces of the Evolver screen (NxEvolver.jsx). Every number is read from the
// backend's receipts; nothing here computes a score of its own.

export function Hash({ value, label = "Copy ID" }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1400); } catch { /* clipboard blocked: the full ID stays in the tooltip */ }
  };
  return (
    <button type="button" className="nx-evo-hash" title={`${value}\n${label}`} aria-label={`${label} ${shortHash(value)}`} onClick={copy}>
      <code>{shortHash(value)}</code>{copied ? <span className="nx-evo-copied">Copied</span> : <Icon as={Copy} size={12} />}
    </button>
  );
}

export function Verdict({ state }) {
  const view = trialState(state);
  return <span className={`nx-evo-verdict is-${view.tone}`}><StatusDot tone={view.tone} pulse={state === "running"} />{view.word}</span>;
}

// ---- Confidence --------------------------------------------------------------

/** Paired gain and its lower confidence bound against zero and the frozen tolerance. */
function ConfidenceStrip({ stat, tolerance = 0 }) {
  const gain = Number(stat?.paired_gain) || 0;
  const low = Number(stat?.lower_confidence_gain) || 0;
  const span = Math.max(Math.abs(gain), Math.abs(low), Math.abs(tolerance), 1e-12) * 1.25;
  const x = value => 44 + (value / span) * 40;
  const ok = stat?.noninferior !== false;
  return (
    <svg className={`nx-evo-ci${ok ? "" : " is-bad"}`} viewBox="0 0 88 14" width="88" height="14" aria-hidden="true">
      <line className="nx-evo-ci-axis" x1="2" x2="86" y1="7" y2="7" />
      <line className="nx-evo-ci-zero" x1={x(0)} x2={x(0)} y1="2" y2="12" />
      {tolerance ? <line className="nx-evo-ci-tol" x1={x(-tolerance)} x2={x(-tolerance)} y1="3" y2="11" /> : null}
      <line className="nx-evo-ci-bar" x1={x(Math.min(low, gain))} x2={x(Math.max(low, gain))} y1="7" y2="7" />
      <circle className="nx-evo-ci-low" cx={x(low)} cy="7" r="2.5" />
      <circle className="nx-evo-ci-gain" cx={x(gain)} cy="7" r="3.5" />
    </svg>
  );
}

function StageStats({ stage, objectives, family }) {
  const names = objectiveOrder(stage.statistics);
  return (
    <div className="nx-evo-table-wrap">
      <table className="nx-evo-table is-stats">
        <thead>
          <tr><th scope="col">Measure</th><th scope="col">Current</th><th scope="col">Candidate</th><th scope="col">Paired gain</th><th scope="col">Lower bound</th><th scope="col"><span className="nx-evo-sr">Confidence</span></th><th scope="col">Verdict</th></tr>
        </thead>
        <tbody>
          {names.map(name => {
            const stat = stage.statistics[name];
            const verdict = objectiveVerdict(stat);
            const direction = objectives?.[name]?.direction === "min" ? "lower is better" : "higher is better";
            return (
              <tr key={name}>
                <th scope="row" title={direction}>{objectiveLabel(name, family)}<span className="nx-evo-dir">{direction}</span></th>
                <td data-label="Current">{formatValue(name, stat.incumbent_mean)}</td>
                <td data-label="Candidate">{formatValue(name, stat.candidate_mean)}</td>
                <td data-label="Paired gain">{formatGain(name, stat.paired_gain)}</td>
                <td data-label="Lower bound" className={stat.noninferior === false ? "is-bad" : ""}>{formatGain(name, stat.lower_confidence_gain)}</td>
                <td className="nx-evo-ci-cell" title={`Sign test p ${Number(stat.sign_p).toPrecision(2)} against corrected α ${Number(stat.alpha).toPrecision(2)} · ${stat.wins ?? 0} wins, ${stat.losses ?? 0} losses`}><ConfidenceStrip stat={stat} tolerance={Number(objectives?.[name]?.tolerance) || 0} /></td>
                <td className="nx-evo-verdict-cell"><span className={`nx-evo-verdict is-${verdict.tone}`}><StatusDot tone={verdict.tone} />{verdict.word}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Pairs({ stage, family }) {
  const [open, setOpen] = useState(false);
  const pairs = stage.pairs || [];
  if (!pairs.length) return null;
  const names = ["success", "tokens"];
  return (
    <div className="nx-evo-pairs">
      <button type="button" className="nx-evo-disclose" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon as={ChevronRight} size={13} className={open ? "is-open" : ""} />{pairs.length} task pairs, same task and seed for both
      </button>
      {open ? (
        <div className="nx-evo-table-wrap">
          <table className="nx-evo-table is-pairs">
            <thead><tr><th scope="col">Task</th><th scope="col">Seed</th><th scope="col">Ran first</th>{names.map(name => <th key={name} scope="col">{objectiveLabel(name, family)}<span className="nx-evo-dir">current → candidate</span></th>)}<th scope="col">Hard checks</th></tr></thead>
            <tbody>
              {pairs.map(pair => {
                const gates = Object.values(pair.candidate?.hard_gates || {}).concat(Object.values(pair.incumbent?.hard_gates || {}));
                return (
                  <tr key={pair.item}>
                    <th scope="row"><code title={pair.item}>{String(pair.item).replace(/^.*-(p\d+-case\d+)$/, "$1")}</code></th>
                    <td><code>{pair.seed}</code></td>
                    <td>{pair.order?.[0] ? (pair.order[0] === stage.incumbent ? "Current" : "Candidate") : "–"}</td>
                    {names.map(name => <td key={name}>{formatValue(name, pair.incumbent?.objectives?.[name])} → {formatValue(name, pair.candidate?.objectives?.[name])}</td>)}
                    <td>{gates.length && gates.every(Boolean) ? "All passed" : <span className="is-bad">Failed</span>}{pair.candidate?.cache_hit ? " · reused" : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

// ---- Trials ------------------------------------------------------------------

function GateStrip({ receipt }) {
  return (
    <ol className="nx-evo-steps" aria-label="Gate steps">
      {gateSteps(receipt).map(step => (
        <li key={step.key} className={`is-${step.state}`}>
          <StatusDot tone={step.state === "passed" ? "green" : step.state === "failed" ? "red" : "idle"} />
          <span>{step.label}</span>
          <span className="nx-evo-step-word">{step.state === "passed" ? "Passed" : step.state === "failed" ? "Failed" : step.state === "blocked" ? "Not reached" : "Not run"}</span>
        </li>
      ))}
    </ol>
  );
}

export function TrialCard({ receipt, domain, family, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const why = explainTrial(receipt, domain.objectives, family);
  const error = splitError(receipt.error);
  const stages = (receipt.stages || []).map(stage => ({ ...stage, incumbent: receipt.incumbent }));
  return (
    <li className={`nx-evo-trial is-${receipt.state}`}>
      <button type="button" className="nx-evo-trial-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon as={ChevronRight} size={14} className={open ? "is-open" : ""} />
        <strong>Trial {receipt.trial_number}</strong>
        <Verdict state={receipt.state} />
        <span className="nx-evo-trial-why">{why.headline}</span>
        <span className="nx-evo-muted nx-evo-trial-time">{when(receipt.finished || receipt.started)}{receipt.elapsed_seconds ? ` · ${seconds(receipt.elapsed_seconds)}` : ""}</span>
      </button>
      {open ? (
        <div className="nx-evo-trial-body">
          <ul className="nx-evo-reasons">{why.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
          {receipt.state === "blocked" && error.detail ? <p className="nx-evo-muted nx-evo-path">Raw model output kept at <code>{error.detail}</code></p> : null}
          <GateStrip receipt={receipt} />
          {stages.map(stage => (
            <section key={`${stage.role}-${stage.panel}`} className="nx-evo-stage">
              <header>
                <h4>{stageLabel(stage)}</h4>
                <span className="nx-evo-muted">{stage.sample_count} tasks · {String(stage.panel).replace(/^.*panel-/, "panel ")}</span>
                {stage.hard_gates_passed === false ? <span className="nx-evo-verdict is-red"><StatusDot tone="red" />Hard check failed</span> : null}
              </header>
              <StageStats stage={stage} objectives={domain.objectives} family={family} />
              <Pairs stage={stage} family={family} />
            </section>
          ))}
          <dl className="nx-evo-facts">
            <div><dt>Candidate</dt><dd><Hash value={receipt.candidate} /></dd></div>
            <div><dt>Compared with</dt><dd><Hash value={receipt.incumbent} /></dd></div>
            <div><dt>Steps reached</dt><dd>{(receipt.levels_reached || []).join(" → ")}</dd></div>
            <div><dt>Checks</dt><dd><Hash value={receipt.manifest_hash} label="Copy locked checks ID" /></dd></div>
            <div><dt>Code</dt><dd><Hash value={receipt.code_hash} label="Copy code ID" /></dd></div>
            <div><dt>Machine</dt><dd>{receipt.hardware?.platform || receipt.hardware?.machine || "–"}</dd></div>
            <div><dt>Receipt</dt><dd><Hash value={receipt.id} label="Copy receipt ID" /></dd></div>
          </dl>
        </div>
      ) : null}
    </li>
  );
}

// ---- Pareto front --------------------------------------------------------------

export function ParetoFront({ domain, family }) {
  const points = frontPoints(domain);
  if (!points.length) {
    return <p className="nx-evo-empty">No measured points yet. A point appears once a trial passes its hard checks on held-out tasks.</p>;
  }
  const tokens = points.map(point => Number(point.scores?.tokens) || 0);
  const success = points.map(point => Number(point.scores?.success) || 0);
  const maxX = Math.max(...tokens) * 1.15 || 1;
  const minY = Math.max(0, Math.floor((Math.min(...success) - 0.1) * 10) / 10);
  const W = 340; const H = 190; const L = 44; const R = 16; const T = 14; const B = 34;
  const x = value => L + (value / maxX) * (W - L - R);
  const y = value => T + (1 - (value - minY) / (1 - minY || 1)) * (H - T - B);
  const yTicks = [minY, (minY + 1) / 2, 1];
  const xTicks = [0, Math.round(maxX / 2 / 100) * 100, Math.round(maxX / 100) * 100].filter((value, index, all) => all.indexOf(value) === index);
  const panel = points[0]?.panel ? String(points[0].panel).replace(/^.*panel-/, "panel ") : "";
  return (
    <div className="nx-evo-front">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Pareto front: ${points.map(point => `${point.role} ${formatValue("success", point.scores?.success)} at ${formatValue("tokens", point.scores?.tokens)} tokens`).join("; ")}`}>
        {yTicks.map(tick => (
          <g key={`y${tick}`}><line className="nx-evo-gridline" x1={L} x2={W - R} y1={y(tick)} y2={y(tick)} /><text className="nx-evo-axis" x={L - 6} y={y(tick) + 3.5} textAnchor="end">{formatValue("success", tick)}</text></g>
        ))}
        {xTicks.map(tick => <text key={`x${tick}`} className="nx-evo-axis" x={x(tick)} y={H - B + 14} textAnchor="middle">{tick.toLocaleString("en-US")}</text>)}
        <text className="nx-evo-axis" x={W - R} y={H - 4} textAnchor="end">Instruction tokens, fewer is better →</text>
        {points.map(point => {
          const cx = x(Number(point.scores?.tokens) || 0);
          const cy = y(Number(point.scores?.success) || 0);
          const right = cx < W - 120;
          return (
            <g key={point.genome} className={`nx-evo-point${point.isCurrent ? " is-current" : ""}${point.confirmed ? "" : " is-unconfirmed"}`} tabIndex={0}>
              <title>{`${point.role}${point.confirmed ? "" : " (not confirmed)"}: ${formatValue("success", point.scores?.success)} ${objectiveLabel("success", family).toLowerCase()}, ${formatValue("tokens", point.scores?.tokens)} tokens, fitness ${formatValue("fitness", point.scores?.fitness)}${point.trialNumber ? `, trial ${point.trialNumber}` : ""}`}</title>
              <circle className="nx-evo-hit" cx={cx} cy={cy} r="12" />
              <circle className="nx-evo-dot" cx={cx} cy={cy} r="5.5" />
              <text className="nx-evo-label" x={right ? cx + 10 : cx - 10} y={cy + 4} textAnchor={right ? "start" : "end"}>{point.role}{point.confirmed ? "" : " · not confirmed"}</text>
            </g>
          );
        })}
      </svg>
      <div className="nx-evo-table-wrap">
        <table className="nx-evo-table is-front">
          <thead><tr><th scope="col">Point</th><th scope="col">{objectiveLabel("success", family)}</th><th scope="col">Tokens</th><th scope="col" title="Success per 1,000 instruction tokens">Fitness</th><th scope="col">Status</th></tr></thead>
          <tbody>
            {points.map(point => (
              <tr key={point.genome}>
                <th scope="row"><span className={`nx-evo-key${point.isCurrent ? " is-current" : ""}${point.confirmed ? "" : " is-unconfirmed"}`} aria-hidden="true" /><span title={point.genome}>{point.role}</span></th>
                <td>{formatValue("success", point.scores?.success)}</td>
                <td>{formatValue("tokens", point.scores?.tokens)}</td>
                <td>{formatValue("fitness", point.scores?.fitness)}</td>
                <td>{point.confirmed ? (point.isCurrent ? "Current version" : "Confirmed") : `Not confirmed${point.trialState === "rejected" ? ", rejected" : ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="nx-evo-muted nx-evo-note">Measured on {panel} ({points[0]?.level}). A point that is not confirmed is a tradeoff, not a winner.</p>
    </div>
  );
}

// ---- Held-out panels -------------------------------------------------------------

export function Panels({ domain }) {
  const rows = panelRows(domain);
  if (!rows.length) return <p className="nx-evo-empty">This version has no task panels.</p>;
  return (
    <ul className="nx-evo-panels">
      {rows.map(row => (
        <li key={row.id} className={row.used ? "is-used" : ""}>
          <span className="nx-evo-panel-name">{row.short}</span>
          <span className="nx-evo-panel-role">{row.role === "discovery" ? "Discovery" : "Held-out"} · {row.count} tasks</span>
          <span className="nx-evo-panel-use">{row.usedBy.length ? row.usedBy.map(use => `Trial ${use.trial}: ${use.label.toLowerCase()}`).join(", ") : row.role === "discovery" ? "Used to pick candidates" : row.used ? "Marked used, so it won't be reused" : "Not used yet"}</span>
        </li>
      ))}
    </ul>
  );
}

// ---- Lineage -----------------------------------------------------------------------

function LineageNode({ node, selected, onSelect, depth = 0 }) {
  const latest = node.trials[node.trials.length - 1];
  return (
    <li className="nx-evo-node" style={{ "--depth": depth }}>
      <button type="button" className={`nx-evo-node-row${selected === node.genome ? " is-on" : ""}`} aria-pressed={selected === node.genome} onClick={() => onSelect(node)}>
        <Icon as={GitBranch} size={13} />
        <code>{shortHash(node.genome)}</code>
        <span className="nx-evo-node-op">{operatorLabel(node.operator)}</span>
        {node.isCurrent ? <span className="nx-evo-chip is-current">Current version</span> : null}
        {node.onFront && !node.isCurrent ? <span className="nx-evo-chip">On the front</span> : null}
        {latest ? <Verdict state={latest.state} /> : null}
        {node.trials.length ? <span className="nx-evo-muted">{node.trials.map(trial => `Trial ${trial.trial_number}`).join(", ")}</span> : null}
      </button>
      {node.children.length ? <ul>{node.children.map(child => <LineageNode key={child.genome} node={child} selected={selected} onSelect={onSelect} depth={depth + 1} />)}</ul> : null}
    </li>
  );
}

function useGenome(domain, genome) {
  const [state, setState] = useState({ status: "idle" });
  useEffect(() => {
    if (!genome) { setState({ status: "idle" }); return undefined; }
    let alive = true;
    setState({ status: "loading" });
    callNx("evolver_genome_command", { domain, genome })
      .then(result => { if (alive) setState({ status: "ready", text: result?.genome?.text ?? JSON.stringify(result?.genome ?? "", null, 2) }); })
      .catch(error => { if (alive) setState({ status: "error", error: error?.message || "That version can't be read." }); });
    return () => { alive = false; };
  }, [domain, genome]);
  return state;
}

function GenomeView({ domain, node }) {
  const own = useGenome(domain, node.genome);
  const parent = useGenome(domain, node.parent || "");
  if (own.status === "loading" || parent.status === "loading") return <div className="nx-evo-empty"><Spinner size={14} /> Reading the stored text</div>;
  if (own.status === "error" || parent.status === "error") return <p className="nx-evo-error">{own.error || parent.error}</p>;
  if (own.status !== "ready") return null;
  const facts = proposalFacts(node.provenance);
  const tokens = text => text.split(/\s+/).filter(Boolean).length;
  if (!node.parent) {
    return (
      <div className="nx-evo-genome">
        <p className="nx-evo-muted">The original text{facts.length ? ` · ${facts.join(" · ")}` : ""} · {tokens(own.text).toLocaleString("en-US")} words</p>
        <pre className="nx-evo-text">{own.text}</pre>
      </div>
    );
  }
  if (parent.status !== "ready") return null;
  const diff = diffLines(parent.text, own.text);
  return (
    <div className="nx-evo-genome">
      <p className="nx-evo-muted">Changes from <code>{shortHash(node.parent)}</code> · <span className="nx-evo-add">+{diff.added}</span> <span className="nx-evo-del">−{diff.removed}</span> lines · {tokens(parent.text).toLocaleString("en-US")} → {tokens(own.text).toLocaleString("en-US")} words{facts.length ? ` · ${facts.join(" · ")}` : ""}</p>
      <div className="nx-evo-diff" role="region" aria-label="Changes from the parent version" tabIndex={0}>
        {diff.rows.map((row, index) => row.type === "fold"
          ? <div key={index} className="nx-evo-diff-fold">{row.count} unchanged lines</div>
          : <div key={index} className={`nx-evo-diff-line is-${row.type}`}><span aria-hidden="true">{row.type === "add" ? "+" : row.type === "del" ? "−" : " "}</span>{row.text || " "}</div>)}
      </div>
    </div>
  );
}

export function Lineage({ domain }) {
  const roots = lineageTree(domain);
  const [selected, setSelected] = useState(null);
  useEffect(() => { setSelected(null); }, [domain.id]);
  if (!roots.length) return <p className="nx-evo-empty">No versions recorded yet.</p>;
  return (
    <div className="nx-evo-lineage">
      <ul className="nx-evo-tree">{roots.map(node => <LineageNode key={node.genome} node={node} selected={selected?.genome} onSelect={setSelected} />)}</ul>
      {selected ? <GenomeView domain={domain.id} node={selected} /> : <p className="nx-evo-muted nx-evo-note">Pick a version to read its text and what changed from its parent.</p>}
    </div>
  );
}

export function LockState({ domain }) {
  const ok = domain.frozen_lock?.ok !== false;
  const count = Object.keys(domain.judge_hashes || {}).length;
  return (
    <span className={`nx-evo-lock${ok ? "" : " is-bad"}`} title={ok ? `${count} judge files match their locked hashes` : domain.frozen_lock?.error}>
      <Icon as={ok ? Lock : LockOpen} size={14} />{ok ? "Checks locked" : "Needs review"}
    </span>
  );
}
