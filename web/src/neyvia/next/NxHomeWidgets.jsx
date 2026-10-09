import { useMemo, useRef } from "react";
import {
  ArrowRight, Bell, Folder, Gauge, GripVertical, LayoutGrid, Loader, Moon, Move, Plus, Scaling, Sprout, X,
} from "lucide-react";
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, rectSortingStrategy, sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import "./nxHome.css";

import { ProviderMark } from "./ProviderMark.jsx";
import { Button, Icon, IconButton, Spinner, StatusDot, ago, elapsed, useTick } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { WIDGETS, addWidget, cycleWidgetSize, hiddenWidgets, moveWidget, nudgeWidget, removeWidget, sizeLabel } from "./nxLayoutModel.js";
import { isNeedsYou, placeSession } from "./nxSidebarModel.js";
import { markFor } from "./NxSidebarParts.jsx";
import { useNightShift } from "./nxNightShiftApi.js";
import { morning } from "./nxNightShiftModel.js";
import { MorningCard } from "./NxNightShiftParts.jsx";

// The home dashboard under the composer (07 §R1 "3 continue cards and the
// Night Shift card"), as widgets the user arranges like a phone home screen:
// press and hold (or Arrange) to wiggle them, drag to reorder, cycle S/M/L,
// remove and add back. Every widget reads real state; when there's nothing to
// show it says so instead of inventing activity.

const ICONS = { continue: Sprout, needs: Bell, running: Loader, nightshift: Moon, projects: Folder, usage: Gauge };
const LIMIT = { s: 2, m: 4, l: 6 };
const HOLD_MS = 550;

function needsText(row) {
  if (row.status === "failed") return "Stopped with an error";
  return row.status === "waiting_input" ? "Waiting for your answer" : "Needs your approval";
}

function ChatLine({ row, onOpen, children }) {
  return (
    <button type="button" className="nx-wline" data-nx-morph="chat" onClick={() => onOpen(row.id)}>
      <ProviderMark id={markFor(row)} size={14} />
      <span className="nx-wline-title">{row.title || "Untitled chat"}</span>
      <span className="nx-wline-meta">{children}</span>
    </button>
  );
}

function Empty({ children }) {
  return <p className="nx-widget-empty">{children}</p>;
}

function ContinueBody({ rows, size, onOpenChat }) {
  const recent = rows.slice(0, size === "l" ? 4 : 2);
  if (!recent.length) return <Empty>Your recent chats come back here, one click from where you left off.</Empty>;
  return (
    <div className="nx-continue">
      {recent.map(row => {
        const place = placeSession(row);
        return (
          <button key={row.id} type="button" className="nx-continue-card" data-nx-morph="chat" onClick={() => onOpenChat(row.id)}>
            <ProviderMark id={markFor(row)} size={18} />
            <span className="nx-continue-eyebrow">Continue</span>
            <span className="nx-continue-title">{row.title || "Untitled chat"}</span>
            <span className="nx-continue-meta">{place.group === "project" ? place.project : "No folder"} · {ago(row.updated_at)}</span>
            <Icon as={ArrowRight} size={15} className="nx-continue-go" />
          </button>
        );
      })}
    </div>
  );
}

function NeedsBody({ rows, size, onOpenChat }) {
  if (!rows.length) return <Empty>Nothing needs you. Agents that wait for an answer or an approval land here.</Empty>;
  return <div className="nx-wlist">{rows.slice(0, LIMIT[size]).map(row => <ChatLine key={row.id} row={row} onOpen={onOpenChat}><StatusDot tone={row.status === "failed" ? "red" : "gold"} />{needsText(row)}</ChatLine>)}</div>;
}

function RunningBody({ rows, size, onOpenChat }) {
  useTick(rows.length > 0, 15000);
  if (!rows.length) return <Empty>No agent is running right now.</Empty>;
  return <div className="nx-wlist">{rows.slice(0, LIMIT[size]).map(row => <ChatLine key={row.id} row={row} onOpen={onOpenChat}><Spinner size={10} />{row.status_since ? elapsed(row.status_since) : "Working"}</ChatLine>)}</div>;
}

const NS_TONE = { running: "live", blocked: "red", waiting: "idle", done: "green" };
/** Night Shift on Home (07 R7.1): the morning card from the measured summary, one click from the board. */
function NightShiftBody({ size, onOpenChat }) {
  const tasks = useOs(state => state.nightshift);
  const { summary } = useNightShift(true);
  const card = useMemo(() => morning(summary), [summary]);
  const list = Object.values(tasks).filter(task => !task.missionId);
  const open = <button type="button" className="nx-link nx-widget-more" onClick={() => os.showPane("mission", "nightshift")}>Open the board</button>;
  if (!list.length && (!card || card.empty)) return <><Empty>No Night Shift tasks yet. Work handed off for the night reports here in the morning.</Empty>{open}</>;
  if (size !== "s" && card) return <><MorningCard data={card} onOpenChat={onOpenChat} compact />{open}</>;
  const count = status => list.filter(task => task.status === status).length;
  return (
    <>
      <div className="nx-wstats">
        <span><strong>{count("done")}</strong> done</span>
        <span><strong>{count("running")}</strong> running</span>
        <span className={count("blocked") ? "is-red" : ""}><strong>{count("blocked")}</strong> blocked</span>
      </div>
      {list.some(task => task.status === "running") ? (
        <div className="nx-wlist">
          {list.filter(task => task.status === "running").slice(0, 1).map(task => (
            <div key={task.id} className="nx-wline is-static">
              <StatusDot tone={NS_TONE[task.status]} pulse />
              <span className="nx-wline-title">{task.title || task.id}</span>
              <span className="nx-wline-meta">running</span>
            </div>
          ))}
        </div>
      ) : null}
      {open}
    </>
  );
}

function ProjectsBody({ rows, size, onOpenChat, onNewChat }) {
  const projects = useMemo(() => {
    const found = new Map();
    for (const row of rows) {
      const place = placeSession(row);
      if (place.group !== "project") continue;
      const known = found.get(place.project) || { name: place.project, path: place.path, count: 0, latest: row };
      known.count += 1;
      if (String(row.updated_at || "") > String(known.latest.updated_at || "")) known.latest = row;
      found.set(place.project, known);
    }
    return [...found.values()].sort((a, b) => String(b.latest.updated_at || "").localeCompare(String(a.latest.updated_at || "")));
  }, [rows]);
  if (!projects.length) return <Empty>Chats started in a folder group into projects here.</Empty>;
  return (
    <div className="nx-wlist">
      {projects.slice(0, LIMIT[size]).map(project => (
        <div key={project.name} className="nx-wproject">
          <button type="button" className="nx-wline" data-nx-morph="chat" onClick={() => onOpenChat(project.latest.id)} title={project.path || project.name}>
            <Icon as={Folder} size={14} />
            <span className="nx-wline-title">{project.name}</span>
            <span className="nx-wline-meta">{project.count} chat{project.count === 1 ? "" : "s"} · {ago(project.latest.updated_at)}</span>
          </button>
          {project.path ? <IconButton icon={Plus} size="sm" label={`New chat in ${project.name}`} onClick={() => onNewChat({ folder: { path: project.path, name: project.name } })} /> : null}
        </div>
      ))}
    </div>
  );
}

function UsageBody() {
  const indicators = useOs(state => state.indicators);
  const usage = indicators.usage;
  const gpu = indicators.gpu;
  if (!usage && !gpu) return <Empty>No usage reported yet. The latest run's new and cached tokens show here.</Empty>;
  return (
    <div className="nx-wusage">
      {usage ? (
        <>
          <strong>{Number.isFinite(usage.used) ? usage.used.toLocaleString() : "—"}</strong>
          <span>{Number.isFinite(usage.cached) ? "new tokens in the latest run" : "tokens in the latest run"}</span>
          {Number.isFinite(usage.cached) && usage.cached > 0 ? <span className="nx-wusage-cached">{usage.cached.toLocaleString()} cached, re-read from the provider's cache</span> : null}
        </>
      ) : null}
      {gpu ? <span className="nx-wusage-gpu">GPU {gpu.busy ? `busy${Number.isFinite(gpu.percent) ? ` ${gpu.percent}%` : ""}` : "idle"}</span> : null}
    </div>
  );
}

function WidgetCard({ widget, arranging, count, children }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: widget.id, disabled: !arranging });
  const hold = useRef(null);
  const meta = WIDGETS[widget.id];
  const cancelHold = () => { if (hold.current) { clearTimeout(hold.current.timer); hold.current = null; } };
  // Press and hold anywhere on a widget to start arranging, like a phone home screen.
  const holdHandlers = arranging ? {} : {
    onPointerDown: event => {
      if (event.button !== 0) return;
      hold.current = { x: event.clientX, y: event.clientY, timer: setTimeout(() => { hold.current = null; navigator.vibrate?.(8); os.arrange(true); }, HOLD_MS) };
    },
    onPointerMove: event => { if (hold.current && Math.hypot(event.clientX - hold.current.x, event.clientY - hold.current.y) > 6) cancelHold(); },
    onPointerUp: cancelHold, onPointerLeave: cancelHold, onPointerCancel: cancelHold,
  };
  return (
    <section ref={setNodeRef} aria-label={meta.title}
      className={`nx-widget is-${widget.size}${arranging ? " is-arranging" : ""}${isDragging ? " is-dragging" : ""}`}
      style={{ transform: CSS.Translate.toString(transform), transition }} {...holdHandlers}>
      <header className="nx-widget-head">
        {arranging ? (
          <button type="button" className="nx-widget-grip" {...attributes} {...listeners} aria-label={`Move ${meta.title}`} aria-roledescription="movable widget">
            <Icon as={GripVertical} size={14} />
          </button>
        ) : <Icon as={ICONS[widget.id]} size={14} className="nx-widget-icon" />}
        <h2>{meta.title}</h2>
        {count ? <span className="nx-widget-count">{count}</span> : null}
        {arranging ? (
          <span className="nx-widget-tools">
            {meta.sizes.length > 1 ? (
              <button type="button" className="nx-widget-size" onClick={() => os.updateLayout(layout => cycleWidgetSize(layout, widget.id))}
                aria-label={`Size: ${sizeLabel(widget.size)}. Change size of ${meta.title}`} title="Change size">
                <Icon as={Scaling} size={12} />{widget.size.toUpperCase()}
              </button>
            ) : null}
            <IconButton icon={X} size="sm" label={`Remove ${meta.title}`} onClick={() => os.updateLayout(layout => removeWidget(layout, widget.id))} />
          </span>
        ) : null}
      </header>
      <div className="nx-widget-body" inert={arranging || undefined}>{children}</div>
    </section>
  );
}

function AddWidget() {
  const layout = useOs(state => state.layout);
  const hidden = hiddenWidgets(layout);
  if (!hidden.length) return null;
  return (
    <section className="nx-widget nx-widget-add is-s" aria-label="Add a widget">
      <header className="nx-widget-head"><Icon as={Plus} size={14} className="nx-widget-icon" /><h2>Add a widget</h2></header>
      <div className="nx-widget-add-list">
        {hidden.map(id => (
          <button key={id} type="button" className="nx-wline" onClick={() => os.updateLayout(current => addWidget(current, id))}>
            <Icon as={ICONS[id]} size={14} /><span className="nx-wline-title">{WIDGETS[id].title}</span><Icon as={Plus} size={13} />
          </button>
        ))}
      </div>
    </section>
  );
}

export function NxHomeWidgets({ rows, onOpenChat, onNewChat }) {
  const layout = useOs(state => state.layout);
  const arranging = useOs(state => state.arranging);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const now = Date.now();
  const data = useMemo(() => {
    const visible = rows.filter(row => !row.archived);
    const recent = [...visible].sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
    return {
      recent,
      needs: recent.filter(row => isNeedsYou(row, now)),
      running: recent.filter(row => row.status === "working"),
      visible,
    };
    // `now` follows rows; the running widget ticks on its own
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows]);

  const body = widget => {
    switch (widget.id) {
      case "continue": return <ContinueBody rows={data.recent} size={widget.size} onOpenChat={onOpenChat} />;
      case "needs": return <NeedsBody rows={data.needs} size={widget.size} onOpenChat={onOpenChat} />;
      case "running": return <RunningBody rows={data.running} size={widget.size} onOpenChat={onOpenChat} />;
      case "nightshift": return <NightShiftBody size={widget.size} onOpenChat={onOpenChat} />;
      case "projects": return <ProjectsBody rows={data.visible} size={widget.size} onOpenChat={onOpenChat} onNewChat={onNewChat} />;
      case "usage": return <UsageBody />;
      default: return null;
    }
  };
  const counts = { needs: data.needs.length, running: data.running.length };

  return (
    <div className={`nx-home${arranging ? " is-arranging" : ""}`}>
      <div className="nx-home-head">
        <span className="nx-home-label"><Icon as={LayoutGrid} size={13} />Your space</span>
        {!arranging && layout.widgets.length ? <span className="nx-home-hint">Press and hold a widget to arrange</span> : null}
        <Button size="sm" icon={Move} onClick={() => os.arrange()} aria-pressed={arranging}>{arranging ? "Done" : "Arrange"}</Button>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter}
        onDragEnd={({ active, over }) => { if (over && active.id !== over.id) os.updateLayout(current => {
          const delta = current.widgets.findIndex(widget => widget.id === over.id) - current.widgets.findIndex(widget => widget.id === active.id);
          return Math.abs(delta) === 1 ? nudgeWidget(current, active.id, delta) : moveWidget(current, active.id, over.id);
        }); }}>
        <SortableContext items={layout.widgets.map(widget => widget.id)} strategy={rectSortingStrategy}>
          <div className="nx-widgets">
            {layout.widgets.map(widget => (
              <WidgetCard key={widget.id} widget={widget} arranging={arranging} count={counts[widget.id]}>{body(widget)}</WidgetCard>
            ))}
            {arranging ? <AddWidget /> : null}
          </div>
        </SortableContext>
      </DndContext>
      {!layout.widgets.length && !arranging ? <p className="nx-widget-empty">No widgets. Choose Arrange to add some back.</p> : null}
    </div>
  );
}
