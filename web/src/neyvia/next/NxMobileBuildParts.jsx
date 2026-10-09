import {useState} from "react";
import {Check, CircleAlert, Copy} from "lucide-react";
import {shortPath} from "./NxPhone.jsx";
import {Icon, IconButton, Spinner, StatusDot, ago, useTick} from "./nxPrimitives.jsx";
export function Missing({ items, title }) {
  if (!items?.length) return null;
  return (
    <div className="nx-ms-missing">
      {title ? <p className="nx-ms-missing-title">{title}</p> : null}
      <ul>
        {items.map(item => (
          <li key={item.id}>
            <span>{item.label}{item.why ? <em> Â· {item.why}</em> : null}</span>
            <strong>{item.size}</strong>
            <code title={item.how}>{item.how}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Check1({ ok, children, detail }) {
  return (
    <li className={`nx-ms-check${ok ? " is-ok" : ""}`}>
      <Icon as={ok ? Check : CircleAlert} size={13} />
      <span>{children}</span>
      {detail ? <em>{detail}</em> : null}
    </li>
  );
}

export function CopyPath({ path }) {
  const [done, setDone] = useState(false);
  if (!path) return null;
  return (
    <span className="nx-ms-path">
      <code title={path}>{shortPath(path)}</code>
      <IconButton size="sm" icon={done ? Check : Copy} label="Copy path" onClick={() => {
        void navigator.clipboard?.writeText(path).then(() => { setDone(true); setTimeout(() => setDone(false), 1400); });
      }} />
    </span>
  );
}

export function JobLine({ job }) {
  useTick(job?.status === "running", 1000);
  if (!job) return null;
  return (
    <div className={`nx-ms-job is-${job.status}`}>
      {job.status === "running" ? <Spinner size={11} /> : <StatusDot tone={job.status === "done" ? "ok" : "error"} />}
      <span>{job.status === "running" ? job.step : job.status === "done" ? "Done" : "Failed"}</span>
      <em>{ago(job.finishedAt || job.startedAt)}</em>
      {job.error ? <pre>{job.error}</pre> : null}
    </div>
  );
}

