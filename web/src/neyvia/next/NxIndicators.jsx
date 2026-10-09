import { useCallback, useMemo, useRef, useState } from "react";
import { Boxes, Cpu, Gauge, LayoutGrid, Moon, Move } from "lucide-react";

import { ProviderMark } from "./ProviderMark.jsx";
import { Icon, Kbd, Popover, Segmented, Spinner, StatusDot, ago } from "./nxPrimitives.jsx";
import { DENSITIES, os, useOs } from "./nxOsStore.js";
import { isNeedsYou } from "./nxSidebarModel.js";
import { markFor } from "./NxSidebarParts.jsx";
import { NxAgentDashboard } from "./NxAgentDashboard.jsx";
import { useRuntimeReading } from "./NxRuntime.jsx";
import { LayaIndicator } from "./NxLaya.jsx";
import { VoiceButton } from "./NxVoice.jsx";
import { evidenceView } from "./nxNightShiftModel.js";
import { Meter, RollingNumber } from "./details/nxDetails.jsx";
import { NxTimers } from "./NxTimers.jsx";

// The 28px strip along the bottom (07 §R3, §R7.5): running agents, Night
// Shift, GPU, usage, the bus, density and the launcher. Each item opens its
// detail. Readings the backend hasn't sent show as "—", never guessed.

const DENSITY_OPTIONS = [{ value: "calm", label: "Calm" }, { value: "workshop", label: "Workshop" }, { value: "grove", label: "Grove" }];
const NS_ORDER = { running: 0, blocked: 1, waiting: 2, done: 3 };
const NS_TONE = { running: "live", blocked: "red", waiting: "idle", done: "green" };

function Item({ label, children, detail, width = 300, tone = "", secondary = false }) {
  const anchor = useRef(null);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button ref={anchor} type="button" className={`nx-ind${secondary ? " nx-strip-secondary" : ""}${tone ? ` is-${tone}` : ""}${open ? " is-open" : ""}`} aria-label={label} title={label}
        aria-expanded={open} onClick={() => setOpen(!open)}>{children}</button>
      <Popover anchor={anchor} open={open} onClose={() => setOpen(false)} placement="top-start" width={width} label={label}>
        <div className="nx-ind-detail" onClick={event => { if (event.target.closest("[data-close]")) setOpen(false); }}>{detail}</div>
      </Popover>
    </>
  );
}

// Agents opens the dashboard (plan 12 §1B); the sidebar's Agents button opens the same one.
function Agents({ rows, onOpenChat }) {
  const anchor = useRef(null);
  const open = useOs(state => state.dashboard);
  const now = Date.now();
  const running = rows.filter(row => row.status === "working");
  const needs = rows.filter(row => isNeedsYou(row, now));
  const marks = [...new Set(running.map(markFor))].slice(0, 3);
  const close = useCallback(() => os.setDashboard(false), []);
  const width = Math.min(460, (globalThis.window?.innerWidth || 460) - 16);
  return (
    <>
      <button ref={anchor} type="button" className={`nx-ind nx-strip-agents${needs.length ? " is-needs" : running.length ? " is-running" : ""}${open ? " is-open" : ""}`}
        aria-label="Agents dashboard" title="Agents: everything working right now" aria-expanded={open} onClick={() => os.setDashboard(!open)}>
        {running.length ? <Spinner size={10} /> : <StatusDot tone="idle" />}
        <span>{running.length ? `${running.length} running` : "No agents running"}</span>
        {marks.map(mark => <ProviderMark key={mark} id={mark} size={12} />)}
        {needs.length ? <span className="nx-ind-badge">{needs.length} need you</span> : null}
      </button>
      <Popover anchor={anchor} open={open} onClose={close} placement="top-start" width={width} label="Agents dashboard">
        <div onClick={event => { if (event.target.closest("[data-close]")) close(); }}>
          <NxAgentDashboard open={open} rows={rows} onOpenChat={onOpenChat} />
        </div>
      </Popover>
    </>
  );
}

function NightShift({ tasks }) {
  const list = Object.values(tasks).sort((a, b) => NS_ORDER[a.status] - NS_ORDER[b.status] || String(a.id).localeCompare(String(b.id)));
  const done = list.filter(task => task.status === "done").length;
  const blocked = list.filter(task => task.status === "blocked").length;
  const running = list.some(task => task.status === "running");
  return (
    <Item label="Night Shift" secondary width={340} tone={blocked ? "error" : running ? "running" : ""} detail={(
      <>
        <strong>Night Shift</strong>
        {list.length ? list.map(task => (
          <div key={task.id} className="nx-ind-task">
            <StatusDot tone={NS_TONE[task.status]} pulse={task.status === "running"} />
            <span className="nx-ind-task-id">{task.id}</span>
            <span className="nx-ind-row-title">{task.title || task.id}</span>
            <span className="nx-ind-task-state">{task.status}</span>
            {task.evidence || task.reason ? <span className="nx-ind-task-note">{task.evidence ? `Evidence: ${evidenceView(task.evidence)?.label}` : task.reason}</span> : null}
          </div>
        )) : <p>No Night Shift tasks yet. Ticked tasks and their evidence appear here as they happen.</p>}
        <button type="button" className="nx-link" data-close onClick={() => os.showPane("mission", "nightshift")}>Open the Night Shift board</button>
      </>
    )}>
      <Icon as={Moon} size={12} />
      {list.length ? (
        <>
          <span>Night Shift <RollingNumber value={done} />/{list.length}</span>
          <Meter value={done} max={list.length} tone={running ? "running" : "ok"} decorative />
          {blocked ? <span className="nx-ind-badge is-error">{blocked} blocked</span> : null}
        </>
      ) : <span>Night Shift idle</span>}
    </Item>
  );
}

function Reading({ label, icon, reading, render, empty }) {
  // No reading yet: say nothing rather than show a bare dash in the strip.
  if (!reading) return null;
  return (
    <Item label={label} secondary width={260} tone={reading?.busy ? "running" : ""} detail={(
      <>
        <strong>{label}</strong>
        <p>{reading ? `${reading.label || label}${reading.at ? ` · updated ${ago(new Date(reading.at).toISOString())}` : ""}` : empty}</p>
      </>
    )}>
      <Icon as={icon} size={12} />
      {render(reading)}
    </Item>
  );
}

const busLabel = bus => (bus.source === "mock" ? "Mock bus" : bus.state === "live" ? "Bus live" : bus.state === "off" ? "Bus off" : bus.state === "offline" ? "Bus offline" : "Bus connecting");

/** Runtimes: opens the harness matrix; after one check it says how many are ready. */
function Runtimes() {
  const reading = useRuntimeReading();
  const stage = useOs(state => state.stage);
  const open = stage?.type === "pane" && stage.kind === "runtime";
  return (
    <button type="button" className={`nx-ind nx-strip-secondary${open ? " is-open" : ""}`} onClick={() => (open ? os.closeStage() : os.showPane("runtime", ""))}
      title="Runtimes: which coding agents are on this PC, their models and limits">
      {reading ? <StatusDot tone={reading.ready ? "green" : "idle"} /> : <Icon as={Boxes} size={12} />}
      <span>{reading ? `${reading.ready} runtime${reading.ready === 1 ? "" : "s"} ready` : "Runtimes"}</span>
    </button>
  );
}

export function NxIndicators({ rows, onOpenChat }) {
  const density = useOs(state => state.density);
  const tasks = useOs(state => state.nightshift);
  const indicators = useOs(state => state.indicators);
  const bus = useOs(state => state.bus);
  const arranging = useOs(state => state.arranging);
  const calm = density === "calm";
  const visible = useMemo(() => rows.filter(row => !row.archived), [rows]);
  return (
    <footer className="nx-strip" aria-label="Status">
      <Agents rows={visible} onOpenChat={onOpenChat} />
      <NxTimers />
      {!calm || Object.keys(tasks).length ? <NightShift tasks={tasks} /> : null}
      {calm ? null : (
        <>
          <Reading label="GPU" icon={Cpu} reading={indicators.gpu} empty="No GPU reading from the backend yet."
            render={gpu => <span>{gpu.busy ? `GPU busy${Number.isFinite(gpu.percent) ? ` ${gpu.percent}%` : ""}` : "GPU idle"}</span>} />
          <Reading label="Usage" icon={Gauge} reading={indicators.usage} empty="No usage reported by the harnesses yet."
            render={usage => (
              <>
                <span>{usage.label || "Usage"}</span>
                {Number.isFinite(usage.used) && Number.isFinite(usage.limit) && usage.limit > 0 ? (
                  <Meter value={usage.used} max={usage.limit} tone={usage.busy ? "running" : "ok"} label={`${usage.used} of ${usage.limit}${usage.unit || ""}`} />
                ) : null}
              </>
            )} />
        </>
      )}
      {calm ? null : <Runtimes />}
      <LayaIndicator calm={calm} />
      <span className="nx-strip-spacer" />
      {/* The command bus only speaks up when it is not simply live: a healthy link is not news. */}
      {bus.state === "live" && bus.source !== "mock" ? null : (
        <span className={`nx-ind is-static nx-bus nx-strip-secondary is-${bus.source === "mock" ? "mock" : bus.state}`} title="Command bus: how the model moves this interface">
          <StatusDot tone={bus.state === "live" ? "caution" : bus.state === "offline" ? "red" : "idle"} />
          <span>{busLabel(bus)}</span>
        </span>
      )}
      <button type="button" className={`nx-ind nx-strip-secondary${arranging ? " is-open" : ""}`} onClick={() => os.arrange()} aria-pressed={arranging}
        title="Move, resize and arrange regions and home widgets">
        <Icon as={Move} size={12} /><span>{arranging ? "Done arranging" : "Arrange"}</span>
      </button>
      <Segmented size="sm" label="Density" value={density} onChange={os.setDensity} options={DENSITY_OPTIONS.filter(option => DENSITIES.includes(option.value))} />
      <VoiceButton />
      <button type="button" className="nx-ind" onClick={() => os.setLauncher(true)} aria-label="Apps">
        <Icon as={LayoutGrid} size={12} /><span>Apps</span><Kbd>Ctrl Space</Kbd>
      </button>
    </footer>
  );
}
