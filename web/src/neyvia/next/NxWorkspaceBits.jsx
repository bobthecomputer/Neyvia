import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { Icon } from "./nxPrimitives.jsx";
import { splitPath, splitPathTail, statusOf } from "./nxWorkspaceModel.js";

/** M / A / D / R / ? / U in a small tinted tile. */
export function StatusBadge({ change }) {
  const status = statusOf(change);
  return <span className={`nx-ws-status is-${status.tone}`} title={status.label} aria-label={status.label}>{status.letter}</span>;
}

/** +12 -3, tabular. A side with nothing on it is left out, and unknown counts (binary files) render nothing. */
export function Counts({ additions, deletions }) {
  const added = Number(additions) || 0;
  const removed = Number(deletions) || 0;
  if (!added && !removed) return null;
  return (
    <span className="nx-ws-counts">
      {added ? <span className="is-add">+{added}</span> : null}
      {removed ? <span className="is-del">{"−"}{removed}</span> : null}
    </span>
  );
}

/** Folder dimmed, file name bright. The folder gives way first when the row is narrow. */
export function FilePath({ path }) {
  const { dir, name } = splitPath(path);
  return (
    <span className="nx-ws-path" title={path}>
      {dir ? <span className="nx-ws-path-dir">{dir}</span> : null}
      <span className="nx-ws-path-name">{name}</span>
    </span>
  );
}

/** A long absolute path, cut in the middle so both the drive and the last folders stay readable. */
export function MiddlePath({ path }) {
  const [head, tail] = splitPathTail(path);
  return (
    <span className="nx-ws-mid" title={path}>
      <span className="nx-ws-mid-head">{head}</span>
      <span className="nx-ws-mid-tail">{tail}</span>
    </span>
  );
}

export function CopyCommand({ text }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    } catch { /* Clipboard denied: the command stays selectable. */ }
  };
  return (
    <span className="nx-ws-cmd">
      <code>{text}</code>
      <button type="button" aria-label={`Copy ${text}`} title="Copy" onClick={copy}><Icon as={done ? Check : Copy} size={13} /></button>
    </span>
  );
}

/** Centered state: a glyph, what happened, what to do. */
export function StateNote({ icon, tone = "", title, children, action }) {
  return (
    <div className={`nx-ws-state${tone ? ` is-${tone}` : ""}`} role={tone === "red" ? "alert" : undefined}>
      <Icon as={icon} size={22} />
      <strong>{title}</strong>
      {children ? <p>{children}</p> : null}
      {action || null}
    </div>
  );
}
