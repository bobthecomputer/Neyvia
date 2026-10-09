import { useEffect, useMemo, useState } from "react";

import { callNx } from "./nxApi.js";
import { rgbToHex, resolveBackground } from "./nxLookModel.js";
import { useOs } from "./nxOsStore.js";
import { useShownTheme } from "./nxSun.js";

// Settings > Look in the running app: your own background picture (kept in
// the PC's state folder by the Settings service), measured once so the
// contrast guard knows how bright or dark it really is.

const LONG_EDGE = 2560;
const GRID = [32, 18];
const cache = new Map(); // image id -> Promise<{ url, samples }>

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("This picture couldn't be opened. Try a PNG, JPEG or WebP file."));
    image.src = src;
  });
}

/** Colours of a coarse grid over the picture (each cell is an average), for the contrast guard. */
export function measure(image) {
  // A picture that can't be measured still shows; the guard then assumes the worst case.
  try { return measureGrid(image); } catch { return null; }
}

function measureGrid(image) {
  const canvas = document.createElement("canvas");
  [canvas.width, canvas.height] = GRID;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return null;
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  // The backdrop covers the window: measure the same centred crop.
  const target = GRID[0] / GRID[1];
  const ratio = image.naturalWidth / image.naturalHeight;
  const sw = ratio > target ? image.naturalHeight * target : image.naturalWidth;
  const sh = ratio > target ? image.naturalHeight : image.naturalWidth / target;
  context.drawImage(image, (image.naturalWidth - sw) / 2, (image.naturalHeight - sh) / 2, sw, sh, 0, 0, GRID[0], GRID[1]);
  const { data } = context.getImageData(0, 0, GRID[0], GRID[1]);
  const samples = [];
  // Transparent cells show the theme behind them; an engine that can't draw the picture leaves every cell
  // transparent, and then the guard keeps assuming the worst instead of trusting empty pixels.
  for (let at = 0; at < data.length; at += 4) if (data[at + 3] >= 128) samples.push(rgbToHex([data[at], data[at + 1], data[at + 2]]));
  return samples.length ? samples : null;
}

const readFile = file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.onerror = () => reject(new Error("This picture couldn't be read."));
  reader.readAsDataURL(file);
});

/** Shrink a chosen file to at most 2560 px on its long edge and save it on the PC. */
export async function uploadBackground(file) {
  if (!file || !/^image\/(png|jpeg|webp|gif|bmp|avif)$/.test(file.type)) throw new Error("Choose a picture file (PNG, JPEG or WebP).");
  const image = await loadImage(await readFile(file));
  const scale = Math.min(1, LONG_EDGE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
  let dataUrl = canvas.toDataURL("image/webp", 0.86);
  if (!dataUrl.startsWith("data:image/webp")) dataUrl = canvas.toDataURL("image/jpeg", 0.88);
  const saved = await callNx("settings_background_save_command", { dataUrl });
  // The data: URL itself is the picture's address: it works in every engine (blob: URLs don't in Obscura).
  cache.set(saved.image, Promise.resolve({ url: dataUrl, samples: measure(await loadImage(dataUrl)) }));
  return saved.image;
}

function loadBackground(id) {
  if (!cache.has(id)) {
    const loading = callNx("settings_background_get_command", { image: id }).then(async ({ dataUrl }) => {
      const image = await loadImage(dataUrl);
      return { url: dataUrl, samples: measure(image) };
    });
    loading.catch(() => cache.delete(id)); // a later render may try again
    cache.set(id, loading);
  }
  return cache.get(id);
}

/** The saved picture as a URL plus its measured colours; null while loading. */
export function useBackgroundImage(id) {
  const [state, setState] = useState({ id: "", url: "", samples: null, error: "" });
  useEffect(() => {
    if (!id) return undefined;
    let alive = true;
    loadBackground(id).then(
      value => { if (alive) setState({ id, url: value.url, samples: value.samples, error: "" }); },
      error => { if (alive) setState({ id, url: "", samples: null, error: error.message || "The background picture couldn't be loaded." }); },
    );
    return () => { alive = false; };
  }, [id]);
  return state.id === id ? state : { id, url: "", samples: null, error: "" };
}

/** Everything the shell needs to draw the current look. */
export function useLookView() {
  const look = useOs(state => state.look);
  const theme = useShownTheme();
  const image = useBackgroundImage(look.background.kind === "image" ? look.background.image : "");
  const background = useMemo(() => resolveBackground(theme, look, image.samples), [theme, look, image.samples]);
  return { look, theme, background, image };
}

/** Root attributes for the shell (and portals): typeface pair, text size, custom background. */
export function lookAttributes(look, background) {
  return {
    "data-nx-font": look.font !== "neyvia" ? look.font : undefined,
    "data-nx-text": look.textSize !== "m" ? look.textSize : undefined,
    "data-nx-bg": background && background.kind !== "theme" ? background.kind : undefined,
  };
}
