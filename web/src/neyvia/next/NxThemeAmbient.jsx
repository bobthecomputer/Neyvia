import { useEffect, useRef, useState } from "react";

import { getOs } from "./nxOsStore.js";
import { useSunState } from "./nxSun.js";
import { horizonAt, minutesOfDay, normalizeSun } from "./nxSunModel.js";

// The ambient layers of the themes that are not Forest or Morning (those are NxKomorebi, Terminal's rain is NxRain), plan 29 THEMES2.
// Each is behind everything that is read, draws once (or is plain CSS) and afterwards moves only by compositor transform or opacity,
// pauses while the page is hidden (data-paused) and is still under reduced motion (nxIdentities.css).
//
//   Sunset       the horizon: a warm band along the bottom edge of the shell whose height and heat follow the real local time
//                (nxSunModel.horizonAt: high in the afternoon, sinking toward evening, a last glow after sunset). Set as two custom properties once a minute.
//   Night Green  dark water: one small canvas of caustic highlights (drawn once, drifting slowly under two different periods)
//                and a faint moon path of glints in the right margin.
//   Terminal     a faint refresh band rolling down the screen once in a while (the scanlines, bloom and rain are CSS and NxRain)
//   Ember        coals: two glows along the bottom edge breathing out of step (opacity only); the sparks stay the existing ones.
// Paper's grain and margin rule and Terminal's scanlines are CSS in nxIdentities.css (they do not move).

const WATER = [256, 144];

function seeded(seed) {
  let state = seed >>> 0;
  return () => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
}

function paintWater(canvas) {
  const started = performance.now();
  const [width, height] = WATER;
  canvas.width = width; canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  const random = seeded(77);
  // Caustics: few, soft, elongated highlights in one sea-green; where they cross they add up into the bright knots water makes.
  context.globalCompositeOperation = "lighter";
  for (let index = 0; index < 34; index += 1) {
    const x = random() * width, y = random() * height, rx = 9 + random() * 20, ry = 2.5 + random() * 5, turn = (random() - 0.5) * 0.9;
    context.save();
    context.translate(x, y); context.rotate(turn); context.scale(1, ry / rx);
    const gradient = context.createRadialGradient(0, 0, 0, 0, 0, rx);
    gradient.addColorStop(0, "rgba(120, 225, 205, 0.5)");
    gradient.addColorStop(0.6, "rgba(120, 225, 205, 0.16)");
    gradient.addColorStop(1, "rgba(120, 225, 205, 0)");
    context.fillStyle = gradient;
    context.beginPath(); context.arc(0, 0, rx, 0, Math.PI * 2); context.fill();
    context.restore();
  }
  globalThis.__nxWater = { drawMs: Math.round((performance.now() - started) * 100) / 100, texture: WATER };
}

function Horizon() {
  const ref = useRef(null);
  useEffect(() => {
    const apply = () => {
      const element = ref.current;
      if (!element) return;
      const { height, glow } = horizonAt(minutesOfDay(new Date()), normalizeSun(getOs().look?.sun));
      element.style.setProperty("--nx-horizon-h", String(Math.round(height * 1000) / 1000));
      element.style.setProperty("--nx-horizon-glow", String(Math.round(glow * 1000) / 1000));
    };
    apply();
    const timer = setInterval(apply, 60000);
    return () => clearInterval(timer);
  }, []);
  return <div ref={ref} className="nx-horizon"><i className="nx-horizon-band" /><i className="nx-horizon-line" /></div>;
}

function Water() {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) paintWater(ref.current); }, []);
  return (
    <div className="nx-water">
      <div className="nx-water-drift"><canvas ref={ref} className="nx-water-caustics" /></div>
      <i className="nx-moonpath" />
    </div>
  );
}

function Scan() {
  return <div className="nx-scan"><i className="nx-crt-roll" /></div>;
}

function Coals() {
  return <div className="nx-coals"><i className="nx-coals-a" /><i className="nx-coals-b" /></div>;
}

export function NxThemeAmbient() {
  const theme = useSunState().shown;
  const [hidden, setHidden] = useState(() => Boolean(globalThis.document?.hidden));
  useEffect(() => {
    const onVisible = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  const layer = theme === "sunset" ? <Horizon /> : theme === "night" ? <Water /> : theme === "ember" ? <Coals /> : theme === "terminal" ? <Scan /> : null;
  return layer ? <div className="nx-themeambient" data-paused={hidden ? "" : undefined} aria-hidden="true">{layer}</div> : null;
}
