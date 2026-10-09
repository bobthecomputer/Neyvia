import { useEffect, useRef, useState } from "react";
import { useOs } from "./nxOsStore.js";
import { useSunState } from "./nxSun.js";

// Forest's canopy (plan 29 FOREST, "Komorebi": sunlight through leaves) and Morning's daylight twin of it (THEMES2:
// the same forest at first light, leaf shadows moving over warm paper, shadow and no light). Three tiny canvases inside the
// ambient layer, behind everything that is read:
//   far    leaf shadows (twigs of pointed leaves) high in the canopy, drifts slowly
//   flecks the light that gets through: soft pools where the canopy opens, each with round pinhole
//          patches of sun, kept out of the reading column
//   sun    the coin's warm light in the two gaps nearest the low sun, shown only while an agent works
//   near   the closest twigs along the top edge and corners, which sway a little in the wind
// Each canvas is drawn once (a few hundred leaves and patches, under 10 ms once) at a small size and stretched by CSS,
// so the GPU holds four small textures and every frame afterwards is a compositor transform or opacity
// change (nxMotion.css "Forest canopy"). Nothing runs on the main thread per frame.
// The drawing is redone only when the light changes: the theme, the time of day, Night Shift starting or stopping.
// Morning draws the same leaves in a green-black shade (--nx-canopy-shade) at low opacity and no flecks: on paper the light is
// the page itself, so the canopy only takes some of it away, which can never lower the contrast of text on it by more than a few percent.
// The time of day comes from the shell's sun source (nxSun.js), so dusk and dawn follow the sunrise and sunset in Settings > Look.
// Paused when the page is hidden (data-paused stops the CSS animations), still under reduced motion
// (the media query and Settings > Motion > Reduce, both in CSS), absent outside Forest and when the
// person chose their own background (data-nx-bg).

const SIZES = { far: [320, 180], near: [256, 144], flecks: [320, 180], sun: [320, 180] };

// A small seeded generator so the canopy is the same canopy every time (no shimmer between reloads).
function seeded(seed) {
  let state = seed >>> 0;
  return () => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
}

function blob(context, x, y, rx, ry, rotation, rgb, alpha) {
  context.save();
  context.translate(x, y);
  context.rotate(rotation);
  context.scale(1, ry / rx);
  const gradient = context.createRadialGradient(0, 0, 0, 0, 0, rx);
  gradient.addColorStop(0, `rgba(${rgb}, ${alpha})`);
  gradient.addColorStop(0.55, `rgba(${rgb}, ${alpha * 0.7})`);
  gradient.addColorStop(1, `rgba(${rgb}, 0)`);
  context.fillStyle = gradient;
  context.beginPath();
  context.arc(0, 0, rx, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

const rgbOf = value => {
  const hex = String(value || "").trim().replace("#", "");
  if (/^[0-9a-f]{6}$/i.test(hex)) return [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16)).join(", ");
  const match = /rgba?\(([^)]+)\)/.exec(String(value || ""));
  return match ? match[1].split(",").slice(0, 3).map(part => part.trim()).join(", ") : "0, 0, 0";
};

// Pools of light sit where the canopy opens: the top-left gap towards the low sun, the top band, the right
// margin and low on the left. Never the middle column where people read.
const POOLS = [
  { x: 0.1, y: 0.1, r: 0.2 }, { x: 0.36, y: 0.02, r: 0.14 }, { x: 0.9, y: 0.22, r: 0.15 },
  { x: 0.07, y: 0.72, r: 0.13 }, { x: 0.93, y: 0.78, r: 0.12 }, { x: 0.66, y: 0.02, r: 0.1 },
];
// The low sun is top-left: while an agent works, its warm light falls through the first two gaps only.
const SUN_POOLS = POOLS.slice(0, 2);

// One leaf, pointed at both ends, as a shadow: the canvas is stretched about five times, so its edge
// comes out as the soft penumbra a real leaf shadow has.
function leaf(context, x, y, length, angle) {
  const width = length * 0.36;
  context.save();
  context.translate(x, y);
  context.rotate(angle);
  context.beginPath();
  context.moveTo(0, 0);
  context.quadraticCurveTo(length * 0.45, -width, length, 0);
  context.quadraticCurveTo(length * 0.45, width, 0, 0);
  context.fill();
  context.restore();
}

// A twig: leaves on alternate sides of a slightly curving stem, smaller towards the tip.
function twig(context, random, x, y, angle, size, count) {
  let px = x, py = y, heading = angle;
  for (let index = 0; index < count; index += 1) {
    const scale = 1 - index / (count * 1.6);
    const side = index % 2 ? 1 : -1;
    leaf(context, px, py, size * scale * (0.8 + random() * 0.4), heading + side * (0.55 + random() * 0.5));
    heading += (random() - 0.5) * 0.35;
    px += Math.cos(heading) * size * 0.42; py += Math.sin(heading) * size * 0.42;
  }
  leaf(context, px, py, size * 0.7, heading);
}

function paint(kind, canvas, tokens) {
  const [width, height] = SIZES[kind];
  canvas.width = width; canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, width, height);
  const random = seeded({ far: 11, near: 23, flecks: 37, sun: 41 }[kind]);
  if (kind === "far" || kind === "near") {
    // Leaf shadow. Far: twigs all over, denser towards the top. Near: a few big twigs reaching in from the
    // top edge and the upper corners, the closest leaves, which sway the most.
    context.fillStyle = `rgba(${tokens.shade}, ${kind === "far" ? 0.75 : 0.9})`;
    context.filter = kind === "far" ? "blur(1.2px)" : "blur(1.6px)";
    const twigs = kind === "far" ? 34 : 9;
    for (let index = 0; index < twigs; index += 1) {
      if (kind === "far") {
        twig(context, random, random() * width, Math.pow(random(), 1.5) * height, random() * Math.PI * 2, 9 + random() * 9, 5 + Math.floor(random() * 5));
      } else {
        const fromTop = index < 5;
        const x = fromTop ? (index / 5 + random() * 0.15) * width : (index % 2 ? width + 4 : -4);
        const y = fromTop ? -4 : (0.08 + random() * 0.35) * height;
        const angle = fromTop ? Math.PI / 2 + (random() - 0.5) * 1.1 : (index % 2 ? Math.PI : 0) + (random() - 0.5) * 0.9;
        twig(context, random, x, y, angle, 14 + random() * 10, 6 + Math.floor(random() * 4));
      }
    }
    context.filter = "none";
    return;
  }
  if (kind === "flecks" && !tokens.flecks) return; // Morning: shadow, not light
  // Light: a soft pool where each gap opens, and inside it the round pinhole images of the sun that make
  // komorebi (round, not streaks: every gap in the leaves is a small camera of the sun).
  const rgb = kind === "sun" ? tokens.sun : tokens.fleck;
  const pools = kind === "sun" ? SUN_POOLS : POOLS;
  const unit = Math.min(width, height);
  for (const pool of pools) {
    const cx = pool.x * width, cy = pool.y * height, reach = pool.r * width;
    blob(context, cx, cy, reach, reach * 0.8, 0, rgb, 0.4);
    const spots = 7 + Math.floor(random() * 6);
    for (let index = 0; index < spots; index += 1) {
      const distance = Math.pow(random(), 0.8) * reach * 0.85, turn = random() * Math.PI * 2;
      const r = unit * (0.008 + random() * 0.022);
      blob(context, cx + Math.cos(turn) * distance, cy + Math.sin(turn) * distance * 0.8, r, r * (0.82 + random() * 0.18), turn, rgb, 0.7 + random() * 0.3);
    }
  }
}

export function NxKomorebi() {
  const sun = useSunState();
  const tasks = useOs(state => state.nightshift);
  const forest = sun.shown === "dark";
  const morning = sun.shown === "light";
  const daylight = sun.daypart;
  const nightShift = forest && Object.values(tasks || {}).some(task => task.status === "running");
  const ref = useRef(null);
  const [hidden, setHidden] = useState(() => Boolean(globalThis.document?.hidden));

  useEffect(() => {
    const onVisible = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  useEffect(() => {
    const root = ref.current;
    if (!(forest || morning) || !root) return;
    const started = performance.now();
    const style = getComputedStyle(root);
    const tokens = {
      shade: rgbOf(style.getPropertyValue("--nx-canopy-shade")),
      fleck: rgbOf(style.getPropertyValue("--nx-fleck")),
      sun: rgbOf(style.getPropertyValue("--nx-sun-patch")),
      flecks: forest,
    };
    for (const canvas of root.querySelectorAll("canvas[data-kind]")) paint(canvas.dataset.kind, canvas, tokens);
    globalThis.__nxKomorebi = { theme: forest ? "dark" : "light", daylight, nightShift, drawMs: Math.round((performance.now() - started) * 100) / 100, textures: SIZES };
  }, [forest, morning, daylight, nightShift]);

  if (!forest && !morning) return null;
  return (
    <div ref={ref} className="nx-komorebi" data-light={forest ? (nightShift ? "deep" : daylight) : "morning"} data-paused={hidden ? "" : undefined} aria-hidden="true">
      <canvas data-kind="far" className="nx-komorebi-far" />
      <canvas data-kind="flecks" className="nx-komorebi-flecks" />
      <canvas data-kind="sun" className="nx-komorebi-sun" />
      <canvas data-kind="near" className="nx-komorebi-near" />
    </div>
  );
}
