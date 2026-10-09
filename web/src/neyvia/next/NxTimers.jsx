import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Timer } from "lucide-react";
import { ackTimer, callTool, subscribeTimers } from "./nxBus.js";
import { elementVisible } from "./nxPaneObserve.js";
import { Icon } from "./nxPrimitives.jsx";

const duration = seconds => {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

// The backend owns the measurement. The local tick only advances the last reading
// between refreshes; unavailable readings never remain on screen as live timers.
export function NxTimers() {
  const [reading, setReading] = useState(null);
  const [now, setNow] = useState(Date.now());
  const pending = useRef(new Map());
  const nodes = useRef(new Map());
  const revision = useRef(0);
  useEffect(() => subscribeTimers(message => {
    const timer = message.payload?.timer;
    if (!timer?.id) return;
    revision.current += 1;
    pending.current.set(String(message.id), timer);
    setReading(current => ({ at: Date.now(), timers: [
      ...(current?.timers || []).filter(row => row.id !== timer.id).map(row => ({ ...row,
        elapsedSeconds: row.elapsedSeconds + Math.max(0, Date.now() - current.at) / 1000 })),
      ...(timer.status === 'running' ? [timer] : []),
    ] }));
  }), []);
  useLayoutEffect(() => {
    for (const [id, timer] of pending.current) {
      const node = nodes.current.get(timer.id);
      if (timer.status === 'running' && (!elementVisible(node) || !node.textContent.includes(timer.label))) continue;
      if (timer.status !== 'running' && node?.isConnected) continue;
      pending.current.delete(id);
      void ackTimer({ id, ok: true }).catch(() => {});
    }
  }, [reading]);
  useEffect(() => {
    let alive = true, busy = false;
    const refresh = async () => {
      if (busy || document.hidden) return;
      busy = true;
      const startedRevision = revision.current;
      try {
        const receipt = await callTool("neyvia.timer.list", { status: "running", limit: 100 });
        const result = receipt.schema === "fluxio.native_tool_receipt.v1" ? receipt.result : receipt;
        if (alive && startedRevision === revision.current) setReading({ timers: result.timers || [], at: Date.now() });
      } catch {
        if (alive) setReading(null);
      } finally { busy = false; }
    };
    void refresh();
    const poll = setInterval(refresh, 3000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { alive = false; clearInterval(poll); clearInterval(tick); };
  }, []);
  if (!reading || now - reading.at > 10000) return null;
  return reading.timers.map(timer => {
    const elapsed = timer.elapsedSeconds + Math.max(0, now - reading.at) / 1000;
    const remaining = timer.targetSeconds == null ? null : timer.targetSeconds - elapsed;
    // Past its target a timer says it is done instead of counting overtime in the bar; the exact overrun stays in the tooltip.
    const done = remaining != null && remaining <= 0;
    const text = remaining == null ? duration(elapsed) : done ? "done" : duration(remaining);
    return <span key={timer.id} ref={node => { if (node) nodes.current.set(timer.id, node); else nodes.current.delete(timer.id); }} data-timer-id={timer.id} className={`nx-ind is-static nx-timer${done ? " is-done" : ""}`} aria-label={`Timer ${timer.label}: ${text}`}
      title={`${timer.label}: ${duration(elapsed)} elapsed${timer.targetSeconds == null ? "" : `, ${duration(timer.targetSeconds)} target${done ? `, done ${duration(-remaining)} ago` : ""}`}`}>
      <Icon as={Timer} size={12} /><span>{timer.label} {text}</span>
    </span>;
  });
}
