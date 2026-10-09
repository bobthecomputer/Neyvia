import { useEffect, useRef } from "react";
import { useOs } from "./nxOsStore.js";
import { useShownTheme } from "./nxSun.js";

// Terminal theme, optional: Matrix rain on a Canvas-2D layer inside the ambient light (behind the chat).
//
// Rules it keeps (plan 29 section 5):
//  - Cheap: one canvas at CSS-pixel size (no devicePixelRatio scaling), ~20 fps, and only the two side bands are
//    drawn, so the rain never falls under the conversation column or anything else that must be read.
//    Trails fade by erasing the bands a little each frame (destination-out), so the canvas stays transparent
//    and the theme's own background shows through. A frame is timed; window.__nxRain holds the numbers.
//  - Paused (no frames at all) when the page is hidden, when motion is reduced (prefers-reduced-motion or
//    Settings > Motion > Reduce), when ambient light is off, or when the screen is too narrow to leave
//    side bands. On pause the canvas is cleared, so a still screen has no rain frozen on it.
//  - Off by default; Settings > Look shows the switch while the Terminal theme is on.

const GLYPHS = "ｦｧｨｩｪｫｬｭｮｯｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789<>/=+*".split("");
const CELL = 16;           // px per column and per row
const FRAME_MS = 50;       // ~20 fps
const MIN_BAND = 72;       // narrower side bands than this are not worth drawing
const THREAD_HALF = 380;   // half of --nx-thread-w (760): the column that stays clear
const GUTTER = 28;

function bands(width) {
  const edge = Math.max(0, width / 2 - THREAD_HALF - GUTTER);
  return edge >= MIN_BAND ? [[0, edge], [width - edge, width]] : [];
}

export function NxRain() {
  const theme = useShownTheme();
  const wanted = useOs(state => state.rain);
  const reduced = useOs(state => state.motion === "reduce");
  const active = theme === "terminal" && wanted && !reduced;
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!active || !canvas) return undefined;
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return undefined;
    const query = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)");
    const stats = { frames: 0, sumMs: 0, maxMs: 0, over1ms: 0, paused: false };
    globalThis.__nxRain = stats;
    let width = 0, height = 0, drops = [], raf = 0, last = 0, colors = null;

    // The head glyphs are drawn once into an atlas; every frame is then drawImage calls (one per column)
    // and one erase per band. Trails are earlier heads fading, so a column needs no second glyph.
    const atlas = document.createElement("canvas");
    let spans = [];
    const readColors = () => {
      const style = getComputedStyle(canvas);
      colors = { head: style.getPropertyValue("--nx-accent-text").trim() || "#6bf5a2" };
      atlas.width = GLYPHS.length * CELL; atlas.height = CELL;
      const paint = atlas.getContext("2d");
      paint.font = `${CELL - 2}px "Geist Mono", "Cascadia Mono", monospace`;
      paint.textBaseline = "top"; paint.fillStyle = colors.head;
      GLYPHS.forEach((glyph, index) => paint.fillText(glyph, index * CELL + 1, 0));
    };
    const resize = () => {
      width = canvas.clientWidth; height = canvas.clientHeight;
      canvas.width = width; canvas.height = height;
      spans = bands(width);
      const columns = spans.flatMap(([from, to]) => Array.from({ length: Math.floor((to - from) / CELL) }, (_, index) => from + index * CELL));
      drops = columns.map(x => ({ x, y: -Math.floor(Math.random() * (height / CELL)), speed: 0.4 + Math.random() * 0.7 }));
    };
    const clear = () => context.clearRect(0, 0, canvas.width, canvas.height);
    const paused = () => document.hidden || query?.matches || !canvas.offsetParent || !drops.length;

    const frame = now => {
      raf = requestAnimationFrame(frame);
      if (now - last < FRAME_MS) return;
      last = now;
      if (paused()) { if (!stats.paused) { clear(); stats.paused = true; } return; }
      stats.paused = false;
      const started = performance.now();
      // Fade what is there inside the two bands only: trails are what is left of earlier frames.
      context.globalCompositeOperation = "destination-out";
      context.fillStyle = "rgba(0, 0, 0, 0.16)";
      for (const [from, to] of spans) context.fillRect(from, 0, to - from, height);
      context.globalCompositeOperation = "source-over";
      context.globalAlpha = 0.85;
      for (const drop of drops) {
        context.drawImage(atlas, ((Math.random() * GLYPHS.length) | 0) * CELL, 0, CELL, CELL, drop.x, Math.floor(drop.y) * CELL, CELL, CELL);
        drop.y += drop.speed;
        if (drop.y * CELL > height && Math.random() > 0.96) { drop.y = -Math.random() * 12; drop.speed = 0.4 + Math.random() * 0.7; }
      }
      context.globalAlpha = 1;
      const took = performance.now() - started;
      stats.frames += 1; stats.sumMs += took; stats.maxMs = Math.max(stats.maxMs, took);
      if (took > 1) stats.over1ms += 1;
      stats.avgMs = stats.sumMs / stats.frames;
    };

    readColors(); resize();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
    observer?.observe(canvas);
    const onVisible = () => { if (document.hidden) clear(); };
    document.addEventListener("visibilitychange", onVisible);
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
      document.removeEventListener("visibilitychange", onVisible);
      clear();
      if (globalThis.__nxRain === stats) delete globalThis.__nxRain;
    };
  }, [active]);

  return active ? <canvas ref={ref} className="nx-rain" aria-hidden="true" /> : null;
}
