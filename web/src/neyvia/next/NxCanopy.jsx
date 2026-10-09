import { useMemo } from "react";
import { Moon, Network } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, Spinner, StatusDot, elapsed, useTick } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { evidenceView } from "./nxNightShiftModel.js";
import { isNeedsYou, placeSession } from "./nxSidebarModel.js";
import { markFor } from "./NxSidebarParts.jsx";

// Grove's always-visible rail (07 §2 "Grove: multiple agents visible and
// mission control"): every agent that is running or waiting on you, across
// projects and harnesses, plus Night Shift at a glance. It is a first look
// at the Canopy; the full mission view comes with the missions backend.

const NS_TONE = { running: "live", blocked: "red", waiting: "idle", done: "green" };

export function NxCanopy({ rows, activeId, onOpenChat }) {
  const tasks = useOs(state => state.nightshift);
  const now = Date.now();
  const active = useMemo(() => rows
    .filter(row => !row.archived && (row.status === "working" || isNeedsYou(row, now)))
    .sort((a, b) => Number(isNeedsYou(b, now)) - Number(isNeedsYou(a, now)) || String(b.updated_at || "").localeCompare(String(a.updated_at || ""))),
  // `now` only changes with the tick below
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [rows]);
  useTick(active.some(row => row.status === "working"), 15000);
  const list = Object.values(tasks);
  const counts = ["running", "waiting", "blocked", "done"].map(status => [status, list.filter(task => task.status === status).length]);

  return (
    <div className="nx-canopy nx-scroll">
      <header className="nx-canopy-head"><Icon as={Network} size={14} /><strong>Canopy</strong><span>{active.length} active</span></header>
      {active.length ? active.map(row => {
        const needs = isNeedsYou(row, now);
        const place = placeSession(row);
        return (
          <button key={row.id} type="button" data-nx-morph="chat" className={`nx-canopy-card${needs ? " is-needs" : " is-running"}${row.id === activeId ? " is-active" : ""}`} onClick={() => onOpenChat(row.id)}>
            <span className="nx-canopy-card-top">
              <ProviderMark id={markFor(row)} size={14} />
              <span className="nx-canopy-card-where">{place.group === "project" ? place.project : "No folder"}</span>
              {row.status === "working" ? <Spinner size={10} /> : <StatusDot tone={row.status === "failed" ? "red" : "gold"} />}
            </span>
            <span className="nx-canopy-card-title">{row.title || "Untitled chat"}</span>
            <span className="nx-canopy-card-state">
              {row.status === "working" ? `Working${row.status_since ? ` · ${elapsed(row.status_since, now)}` : ""}`
                : row.status === "failed" ? "Stopped with an error" : row.status === "waiting_input" ? "Waiting for your answer" : "Needs your approval"}
            </span>
          </button>
        );
      }) : <p className="nx-canopy-empty">Nothing running. Agents that work or wait for you gather here.</p>}

      <header className="nx-canopy-head is-sub"><Icon as={Moon} size={14} /><strong>Night Shift</strong><button type="button" className="nx-link nx-canopy-open" onClick={() => os.showPane("mission", "nightshift")}>Open board</button></header>
      {list.length ? (
        <>
          <div className="nx-canopy-counts">
            {counts.map(([status, count]) => (
              <span key={status} className={count ? "" : "is-zero"}><StatusDot tone={NS_TONE[status]} />{count} {status}</span>
            ))}
          </div>
          {list.filter(task => task.status !== "done").map(task => (
            <div key={task.id} className="nx-canopy-task" title={task.reason || evidenceView(task.evidence)?.label || ""}>
              <StatusDot tone={NS_TONE[task.status]} pulse={task.status === "running"} />
              <span className="nx-canopy-task-id">{task.id}</span>
              <span className="nx-canopy-task-title">{task.title || task.id}</span>
            </div>
          ))}
        </>
      ) : <p className="nx-canopy-empty">No Night Shift tasks yet.</p>}
    </div>
  );
}
