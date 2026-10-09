import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Hand } from "lucide-react";
import "./nxNightShift.css";
import { ProviderMark } from "./ProviderMark.jsx";
import { NxGrowingTree } from "./NxGrowingTree.jsx";
import { Icon, StatusDot } from "./nxPrimitives.jsx";
import { harnessLabel, noteText, stateText, treeLayout } from "./nxNightShiftModel.js";
import { markForHarness } from "./nxMissionsModel.js";

// Shared rendering for Tonight's queue and the live Agents overview.
const LEAF = "M0 0C3.5-5.6 11-6.4 16 0C11 6.4 3.5 5.6 0 0Z";

/** The night as a tree: a leaf per task, a branch per prerequisite level. Done tasks grow full leaves. */
export function NightTree({ board, size = 220, selectedId }) {
  const layout = useMemo(() => treeLayout(board), [board]);
  const running = Boolean(board?.counts?.running);
  const label = board?.tasks?.length ? `${board.counts.done} of ${board.tasks.length} tasks done` : "No tasks yet";
  return (
    <svg className={`nx-ns-tree${running ? " is-running" : ""}`} width={size} height={Math.round((size * layout.height) / layout.width)}
      viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label={label}>
      <circle className="nx-ns-tree-sun" cx={layout.width - 46} cy={34} r={15} />
      <path className="nx-ns-tree-ground" d={`M${layout.mid - 92} ${layout.ground + 2}Q${layout.mid} ${layout.ground - 6} ${layout.mid + 92} ${layout.ground + 2}`} />
      <path className="nx-ns-tree-trunk" d={`M${layout.mid - 4} ${layout.ground}C${layout.mid - 2} ${layout.ground - 30} ${layout.mid - 1.5} ${layout.top + 30} ${layout.mid - 1} ${layout.top}h2C${layout.mid + 1.5} ${layout.top + 30} ${layout.mid + 2} ${layout.ground - 30} ${layout.mid + 4} ${layout.ground}Z`} />
      {layout.branches.map(branch => <path key={branch.key} className="nx-ns-tree-branch" d={branch.d} />)}
      {layout.leaves.map(({ task, x, y, sign }) => {
        const angle = task.status === "blocked" ? 38 : task.status === "done" ? -24 : -32;
        const scale = task.status === "done" ? 1 : task.status === "running" ? 0.78 : task.status === "blocked" ? 0.86 : 0.6;
        const kind = task.status === "waiting" && task.paul ? "needs" : task.status;
        const words = `${task.title || task.id}: ${task.status === "waiting" && task.paul ? "waiting on you" : task.status}`;
        return (
          <g key={task.id} transform={`translate(${x} ${y}) scale(${sign} 1) rotate(${angle})`}>
            {/* keyed by status so a newly done task grows its leaf in */}
            <g key={task.status} className={`nx-ns-leaf is-${kind}${task.id === selectedId ? " is-selected" : ""}`}
              transform={`scale(${scale})`}>
              <title>{words}</title>
              <path d={LEAF} />
            </g>
          </g>
        );
      })}
    </svg>
  );
}

export const TONE = { waiting: "idle", running: "live", blocked: "red", needs_review: "gold", done: "green" };

function TaskCard({ task, selected, onSelect }) {
  const note = noteText(task);
  const tone = task.paul && task.status === "waiting" ? "gold" : TONE[task.status];
  return (
    <button type="button" data-ns-task={task.id} aria-pressed={selected}
      className={`nx-ns-card is-${task.status}${task.paul ? " is-paul" : ""}${task.armed ? " is-armed" : ""}${selected ? " is-selected" : ""}`}
      onClick={() => onSelect(task.id)}>
      <span className="nx-ns-card-top">
        {task.paul ? <Icon as={Hand} size={14} /> : <ProviderMark id={markForHarness(task.harness)} size={18} title={harnessLabel(task.harness)} />}
        <span className="nx-ns-card-route">{task.paul ? "You" : `${harnessLabel(task.harness)}${task.model ? ` · ${task.model}` : ""}`}</span>
        <span className="nx-ns-card-id">{task.id}</span>
      </span>
      <span className="nx-ns-card-title">{task.title || task.id}</span>
      <span className="nx-ns-card-state">
        {task.status === "running" ? <NxGrowingTree size={14} /> : <StatusDot tone={tone} />}
        <span>{stateText(task)}</span>
      </span>
      {note ? <span className="nx-ns-card-note">{note}</span> : null}
      {task.missing?.length ? <span className="nx-ns-card-note is-error">Missing: {task.missing.join(", ")}</span> : null}
    </button>
  );
}

/** Columns in the order work can happen, with a line from each prerequisite to the task that waits for it. */
export function AgentTree({ board, selectedId, onSelect, renderCard, labels, label = "Tasks, in the order they can run" }) {
  const wrap = useRef(null);
  const [lines, setLines] = useState({ width: 0, height: 0, paths: [] });
  const measure = useCallback(() => {
    const root = wrap.current;
    if (!root) return;
    const box = root.getBoundingClientRect();
    const at = id => root.querySelector(`[data-ns-task="${CSS.escape(id)}"]`)?.getBoundingClientRect();
    const paths = board.edges.map((edge, index) => {
      const from = at(edge.from);
      const to = at(edge.to);
      if (!from || !to) return null;
      const x1 = from.right - box.left + root.scrollLeft;
      const y1 = from.top + from.height / 2 - box.top + root.scrollTop;
      const x2 = to.left - box.left + root.scrollLeft;
      const y2 = to.top + to.height / 2 - box.top + root.scrollTop;
      const bend = Math.max(18, (x2 - x1) / 2);
      return { key: `${edge.from}>${edge.to}:${edge.kind || "parent"}:${index}`, d: `M${x1} ${y1}C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`, kind: edge.kind, label: edge.label || edge.kind, done: board.byId.get(edge.from)?.status === "done" };
    }).filter(Boolean);
    setLines({ width: root.scrollWidth, height: root.scrollHeight, paths });
  }, [board]);
  useLayoutEffect(() => {
    measure();
    const observer = new ResizeObserver(() => measure());
    if (wrap.current) observer.observe(wrap.current);
    return () => observer.disconnect();
  }, [measure]);
  return (
    <div ref={wrap} className="nx-ns-graph nx-scroll" aria-label={label}>
      <svg className="nx-ns-edges" width={lines.width} height={lines.height} aria-hidden="true">
        {lines.paths.map(path => <path key={path.key} d={path.d} className={`${path.done ? "is-done" : ""}${path.kind && path.kind !== "parent" ? " is-contact" : ""}`}><title>{path.label || "prerequisite"}</title></path>)}
      </svg>
      {board.levels.map((level, index) => (
        <div key={index} className="nx-ns-level">
          <span className="nx-ns-level-label">{labels?.[index] || (index === 0 ? "First" : `Then (${index})`)}</span>
          {level.map(task => renderCard ? <div key={task.id}>{renderCard(task)}</div> : <TaskCard key={task.id} task={task} selected={task.id === selectedId} onSelect={onSelect} />)}
        </div>
      ))}
    </div>
  );
}

