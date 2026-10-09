import { memo, useEffect, useMemo, useRef, useState } from "react";
import { toBox, renderPdfRaster, pdfCanvasReport } from "./nxPdfModel.js";
import { pdfOutcome } from "./nxOutcomeObservation.js";

// One PDF page: a sized placeholder until it scrolls near view, then the
// canvas, a selectable text layer (pdf.js TextLayer) and our own overlays
// for search hits and highlights. Once the text layer exists, marks are
// measured from the real glyph positions; before that, from PDF geometry.
// Pages far away release their canvas.

/** Boxes (page CSS pixels) of every occurrence of `needle` in the text layer, in reading order. */
function measure(layer, pageElement, needle) {
  const found = [];
  if (!layer || !needle) return found;
  const origin = pageElement.getBoundingClientRect();
  const lower = needle.toLowerCase();
  for (const span of layer.querySelectorAll("span")) {
    const node = [...span.childNodes].find(child => child.nodeType === Node.TEXT_NODE);
    if (!node) continue;
    const hay = node.textContent.toLowerCase();
    for (let at = hay.indexOf(lower); at >= 0; at = hay.indexOf(lower, at + lower.length)) {
      const range = document.createRange();
      range.setStart(node, at);
      range.setEnd(node, at + lower.length);
      const rect = range.getBoundingClientRect();
      found.push({ left: rect.left - origin.left, top: rect.top - origin.top, width: rect.width, height: rect.height });
    }
  }
  return found;
}

export const NxPdfPage = memo(function NxPdfPage({ doc, pdfjs, number, scale, query, hits, activeHit, highlights, onVisible, pageRef, onRendered }) {
  const box = useRef(null);
  const canvas = useRef(null);
  const text = useRef(null);
  const [viewport, setViewport] = useState(null);
  const [near, setNear] = useState(number <= 2);
  const [textReady, setTextReady] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    void doc.getPage(number).then(page => { if (!cancelled) setViewport(page.getViewport({ scale })); });
    return () => { cancelled = true; };
  }, [doc, number, scale]);

  useEffect(() => {
    const element = box.current;
    if (!element) return undefined;
    const nearby = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), { rootMargin: "900px 0px" });
    const seen = new IntersectionObserver(([entry]) => onVisible(number, entry.intersectionRatio), { threshold: [0, 0.25, 0.5, 0.75, 1] });
    nearby.observe(element);
    seen.observe(element);
    return () => { nearby.disconnect(); seen.disconnect(); };
  }, [number, onVisible]);

  useEffect(() => {
    if (!near || !viewport) return undefined;
    let cancelled = false;
    let task = null;
    let layer = null;
    const abort = new AbortController();
    setError('');
    (async () => {
      try {
        const page = await doc.getPage(number);
        if (cancelled) return;
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        const target = canvas.current;
        target.width = Math.floor(viewport.width * ratio);
        target.height = Math.floor(viewport.height * ratio);
        let rendered;
        if (doc.__nxRenderMode === 'mupdf-raster') {
          rendered = await renderPdfRaster(doc, number, viewport.scale * ratio, target, abort.signal);
        } else {
          task = page.render({ canvas: target, canvasContext: target.getContext("2d"), viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
          await task.promise;
          rendered = await pdfCanvasReport(doc, target, number, viewport.scale * ratio);
        }
        if (cancelled || !text.current) return;
        text.current.replaceChildren();
        layer = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: text.current, viewport });
        await layer.render();
        if (!cancelled) { setTextReady(value => value + 1); onRendered({ ...rendered, cssScale: viewport.scale, textReady: true, outcome: pdfOutcome(box.current) }); }
      } catch (reason) {
        if (!cancelled && !['RenderingCancelledException', 'AbortError'].includes(reason?.name)) {
          // Plain words on the page; the technical reason still goes to the state report below.
          setError(/No module named|ImportError|renderer HTTP 5/i.test(String(reason?.message)) ? "This PC can't draw PDF pages yet: its page renderer isn't installed." : "This page couldn't be drawn.");
          onRendered({ number, cssScale: viewport.scale, error: reason?.message || 'Rendering failed' });
        }
      }
    })();
    return () => {
      cancelled = true;
      abort.abort();
      task?.cancel();
      layer?.cancel();
      setTextReady(0);
      if (canvas.current) { canvas.current.width = 0; canvas.current.height = 0; }
      onRendered({ number, cleared: true });
    };
  }, [near, viewport, doc, number, pdfjs, onRendered]);

  // Real glyph boxes once the text layer is there; PDF geometry otherwise.
  const hitBoxes = useMemo(() => {
    if (!viewport) return [];
    const measured = textReady && query ? measure(text.current, box.current, query) : [];
    return hits.map((hit, index) => ({ key: hit.key, style: measured.length === hits.length ? measured[index] : toBox(viewport, hit.rect) }));
  }, [hits, query, viewport, textReady]);
  const markBoxes = useMemo(() => {
    if (!viewport) return [];
    return highlights.flatMap(mark => {
      const measured = mark.anchor === "text" && textReady ? measure(text.current, box.current, mark.text).slice(0, 1) : [];
      const boxes = measured.length ? measured : mark.rects.map(rect => toBox(viewport, rect));
      return boxes.map((style, index) => ({ key: `${mark.id}-${index}`, style, by: mark.by, title: mark.note || mark.text || "" }));
    });
  }, [highlights, viewport, textReady]);

  const size = viewport ? { width: viewport.width, height: viewport.height } : { width: 612 * scale, height: 792 * scale };
  return (
    <div ref={element => { box.current = element; pageRef(number, element); }} className="nx-pdf-page" data-page={number}
      style={{ ...size, "--total-scale-factor": scale }} aria-label={`Page ${number}`}>
      <canvas ref={canvas} className="nx-pdf-canvas" style={size} aria-hidden="true" />
      <div ref={text} className="textLayer" />
      <div className="nx-pdf-marks" aria-hidden="true">
        {markBoxes.map(mark => <span key={mark.key} className={`nx-pdf-mark is-${mark.by || "user"}`} style={mark.style} title={mark.title} />)}
        {hitBoxes.map(hit => <span key={hit.key} className={`nx-pdf-hit${hit.key === activeHit ? " is-active" : ""}`} style={hit.style} />)}
      </div>
      {error ? <p className="nx-pdf-page-error" role="alert">{error}</p> : null}
      <span className="nx-pdf-page-number" aria-hidden="true">{number}</span>
    </div>
  );
});
