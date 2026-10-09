import { useRef, useState } from "react";
import { Check, ChevronDown, Lock, LockOpen, ShieldCheck } from "lucide-react";
import { Icon, Popover, useRovingKeys } from "./nxPrimitives.jsx";

export function PermissionPicker({ modes, value, onChange }) {
  const anchor = useRef(null);
  const listRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(null);
  const onKeyDown = useRovingKeys(listRef);
  if (!modes.length) return null;
  const current = modes.find(mode => mode.id === value) || modes.find(mode => mode.default) || modes[0];
  const wide = /full|bypass|danger/i.test(current?.id || "");
  const close = () => { setOpen(false); setConfirming(null); };
  const choose = mode => {
    if (mode.id === "bypassPermissions") { setConfirming(mode); return; }
    onChange(mode.id); close();
  };
  return (
    <>
      <button ref={anchor} type="button" className={`nx-chip${wide ? " is-warn" : ""}`} aria-haspopup="dialog" aria-expanded={open}
        onClick={() => open ? close() : setOpen(true)} title="Permissions">
        <Icon as={wide ? LockOpen : /ask|manual|default|approval/i.test(current?.id || "") ? Lock : ShieldCheck} size={14} />
        <span className="nx-chip-label">{current?.label || "Permissions"}</span>
        <Icon as={ChevronDown} size={13} className="nx-chip-caret" />
      </button>
      <Popover anchor={anchor} open={open} onClose={close} width={300} label="Permissions">
        {confirming ? (
          <div className="nx-picker nx-route-confirm" role="alertdialog" aria-labelledby="nx-bypass-title" aria-describedby="nx-bypass-description">
            <div className="nx-picker-head" id="nx-bypass-title">Bypass permissions?</div>
            <p className="nx-route-risk" id="nx-bypass-description">Claude Code can run commands and change files without asking. Use this only in a folder you trust.</p>
            <div className="nx-route-actions">
              <button type="button" className="nx-btn nx-btn-sm nx-btn-ghost" onClick={close}>Cancel</button>
              <button type="button" className="nx-btn nx-btn-sm nx-btn-warn" onClick={() => { onChange(confirming.id); close(); }}>Confirm bypass</button>
            </div>
          </div>
        ) : (
          <div className="nx-picker">
            <div className="nx-picker-head">Permissions</div>
            <div role="listbox" ref={listRef} onKeyDown={onKeyDown} className="nx-picker-list">
              {modes.map(mode => (
                <button key={mode.id} type="button" role="option" aria-selected={mode.id === current?.id}
                  className={`nx-picker-row${mode.id === current?.id ? " is-on" : ""}`} onClick={() => choose(mode)}>
                  <span className="nx-picker-main"><strong>{mode.label}</strong>{mode.description ? <span>{mode.description}</span> : null}</span>
                  {mode.id === current?.id ? <Icon as={Check} size={14} className="nx-picker-check" /> : null}
                </button>
              ))}
            </div>
          </div>
        )}
      </Popover>
    </>
  );
}
