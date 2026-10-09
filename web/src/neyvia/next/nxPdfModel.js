// PDF app model (Documents suite, the first two-sided app; plan 08 §4).
import { PDF_CONTRACTS, checkedModelAction } from "./nxModelContracts.js";
import { backendBase } from "./nxApi.js";
// pdf.js loads only when the app opens. Search and highlight geometry are
// kept in PDF space (points, origin bottom-left) so they survive zoom and
// can be sent to or received from the bot side unchanged.

let pdfjsPromise = null;
export function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import("./vendor/pdfjs/pdf.min.mjs").then(async pdfjs => {
      const workerSrc = new URL("./vendor/pdfjs/pdf.worker.min.mjs", import.meta.url).href;
      pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;
      // An engine that loads module workers as classic scripts never answers pdf.js
      // and the document stays "Opening" forever. There, parse on the main thread:
      // pdf.js uses an already-loaded worker module instead of starting a worker.
      if (!(await moduleWorkersWork()) && !globalThis.pdfjsWorker) globalThis.pdfjsWorker = await import(/* @vite-ignore */ workerSrc);
      return pdfjs;
    });
  }
  return pdfjsPromise;
}

function moduleWorkersWork() {
  return new Promise(resolve => {
    let worker = null;
    const done = ok => { clearTimeout(timer); try { worker?.terminate(); } catch { /* already gone */ } resolve(ok); };
    const timer = setTimeout(() => done(false), 2500);
    try {
      // Kept as a plain asset (not bundled as a worker) so the probe really runs as a module.
      const probe = new URL("./vendor/pdfjs/nx-module-probe.mjs", import.meta.url);
      worker = new Worker(probe, { type: "module" });
      worker.addEventListener("message", event => done(event.data === "nx-module-worker"));
      worker.addEventListener("error", () => done(false));
    } catch { done(false); }
  });
}

/** The file name a person reads for a PDF source: an upload's name, a path's last part, or the
 * `path` a file URL carries. Never an encoded route like raw?path=D%3A%5C… */
function _displayName(source) {
  if (source?.file?.name) return String(source.file.name);
  const value = String(source?.value ?? source ?? "").trim();
  const decode = text => { try { return decodeURIComponent(text); } catch { return text; } };
  let path = value;
  if (/^(https?:)?\/\//i.test(value) || value.startsWith("/api/")) {
    try {
      const url = new URL(value, "http://local.invalid");
      path = url.searchParams.get("path") || url.searchParams.get("file") || decode(url.pathname);
    } catch { path = value; }
  }
  const name = decode(path).split(/[\\/]/).filter(Boolean).pop() || "";
  return /^[^?#]+$/.test(name) && name !== "raw" ? name : "document.pdf";
}

export async function openDocument(source) {
  const pdfjs = await loadPdfjs();
  let data = source.data;
  if (!data) {
    const response = await fetch(source.url, { credentials: source.withCredentials ? 'include' : 'same-origin' });
    if (!response.ok) throw Error(`PDF download HTTP ${response.status}`);
    data = new Uint8Array(await response.arrayBuffer());
  }
  const params = { data };
  const doc = await pdfjs.getDocument({ ...params, isEvalSupported: false }).promise;
  doc.__nxRenderMode = faithfulCanvas2d() ? 'pdfjs' : 'mupdf-raster';
  return { pdfjs, doc };
}

function faithfulCanvas2d() {
  const probe = document.createElement('canvas'); probe.width = probe.height = 8;
  const context = probe.getContext('2d');
  if (!context || typeof context.getTransform !== 'function') return false;
  context.translate(3, 3); context.fillStyle = '#ff0000'; context.fillRect(0, 0, 2, 2);
  const matrix = context.getTransform();
  return matrix.e === 3 && matrix.f === 3 && context.getImageData(0, 0, 1, 1).data[3] === 0
    && context.getImageData(3, 3, 1, 1).data[0] === 255;
}

const sha256 = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
  .map(byte => byte.toString(16).padStart(2, '0')).join('');

export async function pdfCanvasReport(doc, target, number, scale) {
  return { number, scale, width: target.width, height: target.height, engine: 'pdfjs',
    sourceSha256: await sha256(await doc.getData()),
    pixelSha256: await sha256(target.getContext('2d').getImageData(0, 0, target.width, target.height).data) };
}

/** A real software raster for engines without working Canvas2D transforms.
 * PDF.js still owns parsing, selectable text, search and page geometry.
 */
export async function renderPdfRaster(doc, number, scale, target, signal) {
  const data = await doc.getData();
  const response = await fetch(`${backendBase()}/api/apps/pdf/raster?page=${number}&scale=${scale}`, {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/pdf' }, body: data, signal,
  });
  if (!response.ok) throw Error((await response.json().catch(() => ({}))).error || `PDF renderer HTTP ${response.status}`);
  const width = Number(response.headers.get('X-PDF-width')), height = Number(response.headers.get('X-PDF-height'));
  const pixels = new Uint8ClampedArray(await response.arrayBuffer());
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0
      || width * height > 8 * 1024 * 1024 || pixels.length !== width * height * 4) throw Error('Invalid PDF raster geometry');
  const sourceSha256 = await sha256(data), pixelSha256 = await sha256(pixels);
  if (sourceSha256 !== response.headers.get('X-PDF-sourceSha256') || pixelSha256 !== response.headers.get('X-PDF-pixelSha256'))
    throw Error('PDF renderer bytes changed during transport');
  if (signal.aborted) throw new DOMException('Rendering cancelled', 'AbortError');
  target.width = width; target.height = height;
  const context = target.getContext('2d'), image = context.createImageData(width, height);
  image.data.set(pixels); context.putImageData(image, 0, 0);
  const canvasSha256 = await sha256(context.getImageData(0, 0, width, height).data);
  if (canvasSha256 !== pixelSha256) throw Error('The browser did not draw the PDF pixels faithfully');
  target.dataset.pdfRenderer = 'mupdf-raster'; target.dataset.pdfPixelHash = canvasSha256;
  return { number, scale, width, height, sourceSha256, pixelSha256: canvasSha256, engine: 'mupdf-raster' };
}

/** Text of every page, fetched once per document and cached on it. */
export async function pageTexts(doc) {
  if (doc.__nxTexts) return doc.__nxTexts;
  const pages = [];
  for (let number = 1; number <= doc.numPages; number += 1) {
    const page = await doc.getPage(number);
    const content = await page.getTextContent();
    pages.push({ page: number, items: content.items.filter(item => typeof item.str === "string" && item.str.length) });
  }
  doc.__nxTexts = pages;
  return pages;
}

/** Rectangle [x1, y1, x2, y2] in PDF space for characters [start, start+length) of a text item. */
function _itemRect(item, start = 0, length = item.str.length) {
  const [, , , d, e, f] = item.transform;
  const height = item.height || Math.abs(d) || 10;
  const total = Math.max(1, item.str.length);
  const x1 = e + (item.width * start) / total;
  const x2 = e + (item.width * (start + length)) / total;
  // Text sits on its baseline; descenders reach a little below it.
  return [x1, f - height * 0.22, x2, f + height * 0.88];
}

/** Every occurrence of `query` (case-insensitive, within one text run). */
function _searchTexts(pages, query, limit = 500) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return [];
  const hits = [];
  for (const { page, items } of pages) {
    for (const item of items) {
      const hay = item.str.toLowerCase();
      let at = hay.indexOf(needle);
      while (at >= 0 && hits.length < limit) {
        hits.push({ page, rect: itemRect(item, at, needle.length), text: item.str.slice(Math.max(0, at - 30), at + needle.length + 30) });
        at = hay.indexOf(needle, at + needle.length);
      }
    }
  }
  return hits;
}

/** Where a highlight goes when the bot side names text instead of rectangles. */
export function rectsForText(pages, pageNumber, text) {
  const hits = searchTexts(pages.filter(page => page.page === pageNumber), text, 20);
  return hits.length ? [hits[0].rect] : [];
}

/** PDF-space rectangle -> CSS box inside a page rendered with `viewport`. */
export function toBox(viewport, rect) {
  const [x1, y1, x2, y2] = viewport.convertToViewportRectangle(rect);
  return { left: Math.min(x1, x2), top: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) };
}

/** Client rectangles of a selection -> PDF-space rectangles on one page. */
export function selectionRects(viewport, pageElement, clientRects) {
  const origin = pageElement.getBoundingClientRect();
  return [...clientRects].filter(rect => rect.width > 1 && rect.height > 1).map(rect => {
    const [ax, ay] = viewport.convertToPdfPoint(rect.left - origin.left, rect.top - origin.top);
    const [bx, by] = viewport.convertToPdfPoint(rect.right - origin.left, rect.bottom - origin.top);
    return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
  });
}

export const ZOOM_STEPS = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3];
function _stepZoom(scale, direction) {
  if (direction > 0) return ZOOM_STEPS.find(step => step > scale + 0.01) ?? ZOOM_STEPS.at(-1);
  return [...ZOOM_STEPS].reverse().find(step => step < scale - 0.01) ?? ZOOM_STEPS[0];
}

const _clampPage = (page, count) => Math.min(Math.max(1, Math.round(Number(page) || 1)), Math.max(1, count || 1));

export function itemRect(item, start = 0, length = item.str.length) { return checkedModelAction(PDF_CONTRACTS, "itemRect", [item, start, length], _itemRect(item, start, length)); }
export function searchTexts(pages, query, limit = 500) { return checkedModelAction(PDF_CONTRACTS, "searchTexts", [pages, query, limit], _searchTexts(pages, query, limit)); }
export function stepZoom(scale, direction) { return checkedModelAction(PDF_CONTRACTS, "stepZoom", [scale, direction], _stepZoom(scale, direction)); }
export const clampPage = (page, count) => checkedModelAction(PDF_CONTRACTS, "clampPage", [page, count], _clampPage(page, count));
export const displayName = source => checkedModelAction(PDF_CONTRACTS, "displayName", [source], _displayName(source));
