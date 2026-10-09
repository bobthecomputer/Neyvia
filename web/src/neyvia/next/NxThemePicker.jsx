import { Moon, Sun } from "lucide-react";

import { THEME_REGISTRY } from "./nxThemeRegistry.js";

// Settings > Look > Theme: one card per registry theme, each a tiny drawing of itself
// (page, sidebar, a card and an action in that theme's own colours) so a person picks by
// sight. A theme that can follow the sun (registry daypair) shows its other half too, split
// diagonally, and a small sun and moon. Radio semantics; arrow keys move like a native radio group.

const byId = Object.fromEntries(THEME_REGISTRY.map(theme => [theme.id, theme]));

/** The look of a theme's day/night twin, in the same shape the drawing needs. */
function twinOf(theme) {
  const pair = theme.daypair;
  if (!pair) return null;
  if (pair.lamp) return { ink: { bg: theme.lamp.bg, sidebar: theme.lamp.sidebar, text: theme.lamp.text, muted: theme.lamp.muted }, panel: theme.lamp.panel, accent: theme.accent };
  return byId[pair.day || pair.night] || null;
}

function Mini({ theme }) {
  return (
    <>
      <i className="nx-themepick-side" style={{ background: theme.ink.sidebar }} />
      <i className="nx-themepick-card-art" style={{ background: theme.panel, boxShadow: `0 0 0 1px ${theme.ink.muted}55` }}>
        <b style={{ background: theme.ink.text }} /><b style={{ background: theme.ink.muted, width: "58%" }} />
      </i>
      <i className="nx-themepick-dot" style={{ background: theme.accent }} />
    </>
  );
}

export function NxThemePicker({ value, onChange }) {
  const move = (event, index) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const next = THEME_REGISTRY[(index + step + THEME_REGISTRY.length) % THEME_REGISTRY.length];
    onChange(next.id);
    event.currentTarget.parentElement.querySelector(`[data-theme-id="${next.id}"]`)?.focus();
  };
  return (
    <div className="nx-themepick" role="radiogroup" aria-label="Theme">
      {THEME_REGISTRY.map((theme, index) => {
        const twin = twinOf(theme);
        return (
          <button key={theme.id} type="button" role="radio" aria-checked={value === theme.id} tabIndex={value === theme.id ? 0 : -1}
            data-theme-id={theme.id} className={`nx-themepick-card${value === theme.id ? " is-on" : ""}`}
            aria-label={`${theme.label}: ${theme.blurb}${twin ? ". Can follow the sun" : ""}`} title={theme.idea}
            onClick={() => onChange(theme.id)} onKeyDown={event => move(event, index)}>
            <span className="nx-themepick-art" aria-hidden="true" style={{ background: theme.ink.bg, color: theme.ink.text }}>
              <Mini theme={theme} />
              {twin ? <span className="nx-themepick-half" style={{ background: twin.ink.bg, color: twin.ink.text }}><Mini theme={twin} /></span> : null}
            </span>
            <span className="nx-themepick-name">{theme.label}
              {twin ? <span className="nx-themepick-sun" aria-hidden="true" title="Can follow the sun"><Sun size={12} /><Moon size={12} /></span> : null}
            </span>
            <span className="nx-themepick-blurb">{theme.blurb}</span>
          </button>
        );
      })}
    </div>
  );
}
