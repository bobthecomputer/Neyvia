import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "lucide-react";

import { backendBase } from "./nxApi.js";
import { Button, Icon, IconButton } from "./nxPrimitives.jsx";
import { os, useOs } from "./nxOsStore.js";
import { sessionsAction } from "./nxBus.js";

// Notices from the bus (`notify`) and the shell's own undo toasts. A notice
// carrying an approvalId is the backend asking before a model action runs.

const ICONS = { info: Info, success: CircleCheck, warning: TriangleAlert, error: CircleAlert };
const LIFETIME = { info: 5000, success: 5000, warning: 12000, error: 12000 };

async function approve(approvalId) {
  const response = await fetch(`${backendBase()}/api/ui/approve`, {
    method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: approvalId }),
  });
  if (!response.ok) throw new Error(`Approval failed (HTTP ${response.status})`);
}

function Toast({ notice, onOpenChat }) {
  const [state, setState] = useState("");
  const sticky = Boolean(notice.approvalId);
  useEffect(() => {
    if (sticky) return undefined;
    const timer = setTimeout(() => os.dismiss(notice.id), (LIFETIME[notice.level] || 5000) + (notice.undo || notice.action ? 5000 : 0));
    return () => clearTimeout(timer);
  }, [notice.id, notice.level, notice.undo, notice.action, sticky]);
  return (
    <div className={`nx-toast is-${notice.level || "info"}`} data-notice-id={notice.id} role={notice.level === "error" || sticky ? "alert" : "status"}>
      <Icon as={ICONS[notice.level] || Info} size={15} />
      <div className="nx-toast-text">
        <span>{notice.message}</span>
        {state && state !== "busy" ? <span className="nx-toast-sub">{state}</span> : null}
      </div>
      {notice.undo ? <Button size="sm" onClick={() => { void sessionsAction(notice.undo.ids, notice.undo.verb, notice.undo.args, notice.undo.patch); os.dismiss(notice.id); }}>Undo</Button> : null}
      {notice.action ? <Button size="sm" onClick={() => { void notice.action.run(); os.dismiss(notice.id); }}>{notice.action.label}</Button> : null}
      {notice.open ? <Button size="sm" onClick={() => { onOpenChat(notice.open); os.dismiss(notice.id); }}>Open</Button> : null}
      {notice.approvalId ? (
        <Button size="sm" variant="outline" disabled={state === "busy"} onClick={async () => {
          setState("busy");
          try { await approve(notice.approvalId); os.dismiss(notice.id); os.notify({ level: "success", message: "Approved. Ask the model to try again." }); }
          catch (error) { setState(error?.message || "Approval failed"); }
        }}>Approve</Button>
      ) : null}
      <IconButton size="sm" icon={X} label="Dismiss" onClick={() => os.dismiss(notice.id)} />
    </div>
  );
}

export function NxToasts({ onOpenChat }) {
  const notices = useOs(state => state.notices);
  if (!notices.length) return null;
  return (
    <div className="nx-toasts" aria-live="polite">
      {notices.map(notice => <Toast key={notice.id} notice={notice} onOpenChat={onOpenChat} />)}
    </div>
  );
}
