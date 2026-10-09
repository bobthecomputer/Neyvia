import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Coins, Puzzle, SquareTerminal, TriangleAlert } from "lucide-react";

import { callTool } from "./nxBus.js";
import { Icon, Popover, local, useRovingKeys } from "./nxPrimitives.jsx";

const PREFERRED = "claude.transport";
const ACKNOWLEDGED = "claude.transport.riskAck";

/** The route this person last chose for Claude Code, when the app offers one. */
export function preferredTransport(transports) {
  if (!transports?.length) return null;
  const saved = local.get(PREFERRED, null);
  const entry = transports.find(item => item.id === saved && item.available !== false);
  return (entry || transports.find(item => item.default) || transports[0]).id;
}

/** One line under the model list saying where messages from Neyvia are billed. */
export function billingNote(options, transport) {
  if (!options?.transports?.length) return null;
  const auth = options.auth;
  if (auth && !["subscription", "unknown"].includes(auth.kind)) {
    return `Claude Code on this PC is set up with ${auth.label}, so messages from Neyvia are billed there.`;
  }
  return transport === "terminal"
    ? "Messages from Neyvia start Claude Code's interactive mode on your PC and count against your plan's usual limits."
    : "Messages from Neyvia run Claude Code's print mode (claude -p) and use your monthly Agent SDK credit.";
}

export function RoutePicker({ transports, value, onChange }) {
  const anchor = useRef(null);
  const listRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(null);
  const onKeyDown = useRovingKeys(listRef);
  if (!transports?.length) return null;
  const current = transports.find(item => item.id === value) || transports.find(item => item.default) || transports[0];
  const pending = transports.find(item => item.id === confirming);
  const note = transports.find(item => item.note)?.note;
  const close = () => { setOpen(false); setConfirming(null); };
  const choose = entry => {
    if (entry.available === false) return;
    if (entry.risk && !local.get(ACKNOWLEDGED, false)) { setConfirming(entry.id); return; }
    local.set(PREFERRED, entry.id);
    onChange(entry.id);
    close();
  };
  return (
    <>
      <button ref={anchor} type="button" className={`nx-chip${current.risk ? " is-warn" : ""}`} aria-haspopup="dialog" aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))} title="How Claude Code runs, and what it uses">
        <Icon as={current.risk ? SquareTerminal : Coins} size={14} />
        <span className="nx-chip-label">{current.label}</span>
        <Icon as={ChevronDown} size={13} className="nx-chip-caret" />
      </button>
      <Popover anchor={anchor} open={open} onClose={close} width={344} label="How Claude Code runs">
        {pending ? (
          <div className="nx-picker nx-route-confirm" role="alertdialog" aria-labelledby="nx-route-risk-title">
            <div className="nx-picker-head" id="nx-route-risk-title"><Icon as={TriangleAlert} size={13} /> Plan limits carries some risk</div>
            <p className="nx-route-risk">{pending.risk}</p>
            <p className="nx-route-what">{pending.description}</p>
            {pending.limits?.length ? (
              <ul className="nx-route-limits">{pending.limits.map(limit => <li key={limit}>{limit}</li>)}</ul>
            ) : null}
            <div className="nx-route-actions">
              <button type="button" className="nx-btn nx-btn-sm nx-btn-ghost" onClick={() => setConfirming(null)}>Keep Agent SDK credit</button>
              <button type="button" className="nx-btn nx-btn-sm nx-btn-warn" onClick={() => { local.set(ACKNOWLEDGED, true); choose(pending); }}>
                I understand, use plan limits
              </button>
            </div>
          </div>
        ) : (
          <div className="nx-picker">
            <div className="nx-picker-head">How Claude Code runs</div>
            <div role="listbox" ref={listRef} onKeyDown={onKeyDown} className="nx-picker-list">
              {transports.map(entry => (
                <button key={entry.id} type="button" role="option" aria-selected={entry.id === current.id} disabled={entry.available === false}
                  className={`nx-picker-row${entry.id === current.id ? " is-on" : ""}`} onClick={() => choose(entry)}>
                  <span className="nx-picker-main">
                    <strong>{entry.label}{entry.risk ? <span className="nx-tag is-warn">Some risk</span> : null}</strong>
                    <span>{entry.available === false ? entry.reason : entry.description}</span>
                  </span>
                  {entry.id === current.id ? <Icon as={Check} size={14} className="nx-picker-check" /> : null}
                </button>
              ))}
            </div>
            {transports.some(entry => entry.id === "terminal") ? <ModsSwitch /> : null}
            {note ? <p className="nx-picker-foot">{note}</p> : null}
          </div>
        )}
      </Popover>
    </>
  );
}

/** Plan-limits runs start Claude Code with the Neyvia plugin (neyvia.claude.mods); on unless switched off here. */
function ModsSwitch() {
  const [mods, setMods] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    callTool("neyvia.claude.mods", {})
      .then(receipt => { if (live) setMods(receipt?.result || null); })
      .catch(() => { if (live) setError("Couldn't read this setting from the PC."); });
    return () => { live = false; };
  }, []);
  const toggle = async enabled => {
    setBusy(true);
    setError("");
    try {
      const receipt = await callTool("neyvia.claude.mods", { enabled });
      setMods(receipt?.result || { ...mods, enabled });
    } catch (failure) {
      setError(failure?.message || "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  };
  const on = mods ? mods.enabled !== false : true;
  const blocked = mods && mods.available === false;
  return (
    <label className={`nx-route-mods${on && !blocked ? " is-on" : ""}`}>
      <input type="checkbox" role="switch" checked={on && !blocked} disabled={!mods || busy || blocked}
        onChange={event => toggle(event.target.checked)} />
      <Icon as={Puzzle} size={14} />
      <span className="nx-route-mods-text">
        <strong>Neyvia tools in Claude Code</strong>
        <span>{blocked ? mods.reason : error || "On plan limits, Claude Code starts with the Neyvia plugin: Neyvia's tools and manuals, and a live checklist here. Claude Code still asks before using a tool."}</span>
      </span>
    </label>
  );
}
