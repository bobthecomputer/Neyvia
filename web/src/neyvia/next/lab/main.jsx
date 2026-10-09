import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";

import "../../neyviaFonts.css";
import { THEME_REGISTRY } from "../nxThemeRegistry.js";
import "../nxTokens.css";
import "../nxThemes.css";
import "../nxShell.css";
import "../nxOs.css";
import "./lab.css";
import { Segmented, useMedia } from "../nxPrimitives.jsx";

// Design lab (dev only: http://127.0.0.1:<vite port>/design-lab.html). Renders
// every specimen in ./specimens inside a real `.nx` root with the real tokens,
// themes and primitives, so a component can be checked in each theme and at
// phone width before it goes into the shell. URL: ?theme=dark|light|sunset|night
// (default follows the browser's light/dark setting: light = Morning, dark = Forest)
// and ?only=<specimen file name>. The design manual's check loop points here.

const THEMES = THEME_REGISTRY.map(theme => ({ value: theme.id, label: theme.label }));
const SPECIMENS = Object.entries(import.meta.glob("./specimens/*.jsx", { eager: true }))
  .map(([path, module]) => ({ id: path.slice(12, -4), title: module.title || path.slice(12, -4), View: module.default }))
  .filter(item => typeof item.View === "function")
  .sort((a, b) => a.id.localeCompare(b.id));

const params = new URLSearchParams(window.location.search);

function useTheme() {
  const prefersDark = useMedia("(prefers-color-scheme: dark)");
  const asked = params.get("theme");
  const [theme, setTheme] = useState(THEMES.some(item => item.value === asked) ? asked : null);
  const choose = value => {
    const next = new URLSearchParams(window.location.search);
    next.set("theme", value);
    window.history.replaceState(null, "", `${window.location.pathname}?${next}`);
    setTheme(value);
  };
  return [theme || (prefersDark ? "dark" : "light"), choose];
}

function Lab() {
  const [theme, setTheme] = useTheme();
  const phone = useMedia("(max-width: 760px)");
  const only = params.get("only");
  const shown = only ? SPECIMENS.filter(item => item.id === only) : SPECIMENS;
  return (
    <div className={`nx nx-root nx-lab${phone ? " is-phone" : ""}`} data-nx-theme={theme} data-nx-density="workshop">
      <header className="nx-lab-head">
        <strong>Design lab</strong>
        <Segmented label="Theme" size="sm" value={theme} options={THEMES} onChange={setTheme} />
      </header>
      <main className="nx-lab-body">
        {shown.length ? shown.map(({ id, title, View }) => (
          <section key={id} className="nx-lab-specimen" aria-label={title} data-specimen={id}>
            <h2>{title}</h2>
            <View />
          </section>
        )) : <p className="nx-lab-empty">No specimen called “{only}”. Add one to web/src/neyvia/next/lab/specimens.</p>}
      </main>
    </div>
  );
}

// Hot reload re-runs this module; reuse the root instead of creating a second one.
window.__nxLabRoot ||= createRoot(document.getElementById("lab"));
window.__nxLabRoot.render(<StrictMode><LazyMotion features={domAnimation} strict><MotionConfig reducedMotion="user"><Lab /></MotionConfig></LazyMotion></StrictMode>);
