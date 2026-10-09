import { useCallback, useEffect, useState } from "react";
import { Check, Copy, Download, Package, ReceiptText, RotateCcw, TriangleAlert } from "lucide-react";

import { Button, Icon, Spinner } from "./nxPrimitives.jsx";
import { callNx } from "./nxApi.js";
import { formatBytes, packView, packsBusy, plainMissing } from "./nxOnboardingModel.js";

// Add-on packs in setup: each one installs on its own through
// onboarding_pack_install_command (the same call as neyvia.onboarding.pack),
// shows its progress while the copy runs, and keeps a receipt once every file
// passed its checksum. Packs that aren't packaged yet say what is missing.

/** Install state of every pack, refreshed while one is copying. */
export function usePackStatus(open) {
  const [statuses, setStatuses] = useState({});
  const [error, setError] = useState("");
  const merge = useCallback(result => {
    const rows = result?.packs || [];
    setStatuses(current => ({ ...current, ...Object.fromEntries(rows.map(row => [row.packId, row])) }));
  }, []);
  const refresh = useCallback(() => callNx("onboarding_pack_status_command").then(result => { merge(result); setError(""); })
    .catch(failure => setError(failure?.message || "Add-on status didn't load.")), [merge]);

  useEffect(() => { if (open) void refresh(); }, [open, refresh]);
  const busy = packsBusy(statuses);
  useEffect(() => {
    if (!open || !busy) return undefined;
    const timer = setInterval(() => void refresh(), 700);
    return () => clearInterval(timer);
  }, [open, busy, refresh]);

  const install = useCallback(async packId => {
    setStatuses(current => ({ ...current, [packId]: { ...(current[packId] || {}), packId, state: "queued", error: "" } }));
    try { merge(await callNx("onboarding_pack_install_command", { packId })); } catch (failure) {
      setStatuses(current => ({ ...current, [packId]: { ...(current[packId] || {}), packId, state: "failed", error: failure?.message || "The install didn't start." } }));
    }
  }, [merge]);
  return { statuses, error, install };
}

function Receipt({ status }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="nx-onb-pack-more">
      <p>Every file was copied into Neyvia's add-on folder and passed its checksum. Nothing else on this PC was changed.</p>
      <dl>
        {status.version ? <div><dt>Version</dt><dd>{status.version}</dd></div> : null}
        {status.finishedAt ? <div><dt>Installed</dt><dd>{new Date(status.finishedAt).toLocaleString()}</dd></div> : null}
        {status.totalBytes ? <div><dt>Size</dt><dd>{formatBytes(status.totalBytes)}</dd></div> : null}
        {status.contents?.length ? <div><dt>Contains</dt><dd>{status.contents.map(path => path.split("/").pop()).join(", ")}</dd></div> : null}
      </dl>
      {status.receipt ? (
        <div className="nx-onb-command">
          <code title={status.receipt}>{status.receipt}</code>
          <Button variant="ghost" size="sm" icon={copied ? Check : Copy} onClick={() => { void navigator.clipboard?.writeText(status.receipt).then(() => setCopied(true)); }}>{copied ? "Copied" : "Copy"}</Button>
        </div>
      ) : null}
      {status.missing?.length ? <p className="nx-onb-fine">Still to come: {status.missing.map(plainMissing).join(" ")}</p> : null}
    </div>
  );
}

function Missing({ items }) {
  return (
    <div className="nx-onb-pack-more">
      <p>This pack isn't packaged yet. What it still needs:</p>
      <ul>{items.map(item => <li key={item} title={item}>{plainMissing(item)}</li>)}</ul>
    </div>
  );
}

/** The service's raw refusals, in words a person can act on. */
const plainPackDetail = text => (/ed25519|signature/i.test(text || "") ? "Not signed for release yet, so it can't be installed from here." : text);

export function PackRow({ pack, status, onInstall, unlocks = [] }) {
  const view = packView(pack, status);
  const [open, setOpen] = useState(false);
  const toggle = view.state === "installed" || view.state === "unavailable";
  return (
    <div className={`nx-onb-pack is-${view.state}${open ? " is-open" : ""}`}>
      <div className="nx-onb-pack-head">
        <span className="nx-onb-pack-icon">
          {view.state === "installed" ? <Icon as={Check} size={15} /> : view.busy ? <Spinner size={13} /> : view.state === "failed" ? <Icon as={TriangleAlert} size={15} /> : <Icon as={Package} size={15} />}
        </span>
        <span className="nx-onb-pack-name">
          <b>{pack.name}</b>
          <small className={view.state === "failed" ? "is-error" : ""}>{plainPackDetail(view.detail)}</small>
          {unlocks.length ? <small className="nx-onb-pack-unlocks">For {unlocks.join(", ")}</small> : null}
        </span>
        {view.canInstall ? (
          <Button variant={view.state === "failed" ? "outline" : "primary"} size="sm" icon={view.state === "failed" ? RotateCcw : Download}
            onClick={() => onInstall(pack.id)}>{view.state === "failed" ? "Try again" : "Install"}</Button>
        ) : null}
        {view.busy ? <span className="nx-onb-pack-pct">{view.percent}%</span> : null}
        {toggle ? (
          <Button variant="ghost" size="sm" icon={view.state === "installed" ? ReceiptText : undefined} aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Hide" : view.state === "installed" ? "Receipt" : "What's missing"}
          </Button>
        ) : null}
      </div>
      {view.busy ? (
        <div className="nx-onb-meter" role="progressbar" aria-label={`Installing ${pack.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={view.percent}>
          <i style={{ width: `${Math.max(view.percent, 4)}%` }} />
        </div>
      ) : null}
      {open && view.state === "installed" ? <Receipt status={status} /> : null}
      {open && view.state === "unavailable" ? <Missing items={view.missing} /> : null}
    </div>
  );
}

/** Suggested packs first; then the rest that can be installed now; the ones not packaged yet last. */
export function PacksSection({ packs, suggested, statuses, error, onInstall, unlocks = {} }) {
  const byId = Object.fromEntries(packs.map(pack => [pack.id, pack]));
  const first = suggested.map(id => byId[id]).filter(Boolean);
  const rest = packs.filter(pack => !suggested.includes(pack.id));
  const now = rest.filter(pack => packView(pack, statuses[pack.id]).state !== "unavailable");
  const later = rest.filter(pack => packView(pack, statuses[pack.id]).state === "unavailable");
  const installed = packs.filter(pack => statuses[pack.id]?.state === "installed").length;
  const row = pack => <PackRow key={pack.id} pack={pack} status={statuses[pack.id]} onInstall={onInstall} unlocks={unlocks[pack.id]} />;
  return (
    <section className="nx-onb-packs">
      {installed ? <p className="nx-onb-fine"><span className="nx-onb-count">{installed} installed</span></p> : null}
      {error ? <p className="nx-onb-error"><Icon as={TriangleAlert} size={14} /> {error}</p> : null}
      {first.length ? <div className="nx-onb-packlist">{first.map(row)}</div> : <p className="nx-onb-fine">Pick what you will use Neyvia for and the matching packs show here first.</p>}
      {now.length ? (
        <details className="nx-onb-more">
          <summary>{first.length ? "Other packs" : "All packs"} you can install now · {now.length}</summary>
          <div className="nx-onb-packlist">{now.map(row)}</div>
        </details>
      ) : null}
      {later.length ? (
        <details className="nx-onb-more">
          <summary>Not packaged yet · {later.length}</summary>
          <div className="nx-onb-packlist">{later.map(row)}</div>
        </details>
      ) : null}
      <p className="nx-onb-fine">Come back to this step any time from Setup in the sidebar.</p>
    </section>
  );
}
