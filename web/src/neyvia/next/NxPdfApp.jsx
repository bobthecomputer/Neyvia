import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, Trash2 } from "lucide-react";

import "./nxPdf.css";
import { NxPdfPage } from "./NxPdfPage.jsx";
import { NxPdfToolbar } from "./NxPdfToolbar.jsx";
import { Button, Icon, local } from "./nxPrimitives.jsx";
import { backendBase } from "./nxApi.js";
import { os, useOs } from "./nxOsStore.js";
import { reportAppState } from "./nxBus.js";
import { clampPage, displayName, openDocument, pageTexts, rectsForText, searchTexts, selectionRects, stepZoom } from "./nxPdfModel.js";

// The PDF app's user side. Both sides act on the same state: the model's
// pdf.* commands arrive through the bus inbox, and what Paul sees (file,
// visible page, zoom, search, selection, highlights) is reported back with
// reportAppState so the bot side knows where he is.

/** What went wrong, in words: never a raw HTTP code or library message. */
function plainPdfError(error) {
  const text = String(error?.message || "");
  if (/HTTP 40[13]/.test(text)) return "Neyvia isn't allowed to read that file.";
  if (/HTTP 404/.test(text)) return "That file isn't there any more.";
  if (/HTTP|fetch|network/i.test(text)) return "The file couldn't be read from this PC.";
  if (/password/i.test(text)) return "This PDF is locked with a password.";
  if (/Invalid PDF|structure|corrupt/i.test(text)) return "This file isn't a readable PDF.";
  return "This PDF couldn't be opened.";
}

const isUrl = value => /^https?:\/\//i.test(value);
const fileKey = source => (source?.file ? `${source.file.name}:${source.file.size}` : source?.value || "");

/** A PC path is read through the bot side (proposed GET /api/apps/pdf/file?path=). */
function toParams(source) {
  if (source.file) return source.file.arrayBuffer().then(data => ({ data }));
  if (isUrl(source.value)) return Promise.resolve({ url: source.value });
  return Promise.resolve({ url: `${backendBase()}/api/apps/pdf/file?path=${encodeURIComponent(source.value)}`, withCredentials: true });
}

export function NxPdfApp({ target }) {
  const [source, setSource] = useState(() => (target ? { value: target } : null));
  const [loaded, setLoaded] = useState({ status: "idle" });
  const [scale, setScale] = useState(1);
  const [fitWidth, setFitWidth] = useState(true);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState({ query: "", hits: [], active: 0, busy: false });
  const [selection, setSelection] = useState(null);
  const [marks, setMarks] = useState([]);
  const [marksOpen, setMarksOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [renderedPages, setRenderedPages] = useState({});
  const onRendered = useCallback(report => setRenderedPages(current => {
    const next = { ...current };
    if (report.cleared) delete next[report.number]; else next[report.number] = report;
    return next;
  }), []);
  const inbox = useOs(state => state.inbox);
  const scroller = useRef(null);
  const picker = useRef(null);
  const searchRef = useRef(null);
  const pageEls = useRef(new Map());
  const visible = useRef(new Map());
  const pendingPage = useRef(null);
  const { doc, pdfjs } = loaded;
  const pages = doc?.numPages || 0;
  const key = fileKey(source);
  const recent = loaded.status === "idle" ? local.get("pdf.recent", []) : [];

  useEffect(() => { if (target) setSource({ value: target }); }, [target]);

  // Load the document whenever the source changes.
  useEffect(() => {
    if (!source) { setLoaded({ status: "idle" }); return undefined; }
    let cancelled = false;
    let opened = null;
    setLoaded({ status: "loading", name: displayName(source) });
    setSearch({ query: "", hits: [], active: 0, busy: false });
    setQuery(""); setSelection(null); setPage(1); visible.current.clear();
    setRenderedPages({});
    // A document that never answers must not leave "Opening…" on screen forever.
    let late = false;
    const slow = setTimeout(() => { late = true; if (!cancelled) setLoaded({ status: "error", name: displayName(source), error: "It took too long to open. Try again, or choose another PDF." }); }, 45000);
    toParams(source).then(openDocument).then(result => {
      clearTimeout(slow);
      opened = result.doc;
      if (cancelled || late) { void opened.destroy(); return; }
      const name = displayName(source);
      setLoaded({ status: "ready", ...result, name });
      // Remember PDFs opened from a path (not uploads) so the empty desk can offer them again.
      if (!source.file) local.set("pdf.recent", [{ value: source.value, name, pages: result.doc?.numPages || 0, at: Date.now() }, ...local.get("pdf.recent", []).filter(row => row.value !== source.value)].slice(0, 5));
    }).catch(error => {
      clearTimeout(slow);
      if (!cancelled && !late) setLoaded({ status: "error", name: displayName(source), error: plainPdfError(error) });
    });
    return () => { cancelled = true; clearTimeout(slow); void opened?.destroy(); };
  }, [source]);

  useEffect(() => { setMarks(key ? local.get(`pdf.marks.${key}`, []) : []); }, [key]);
  const saveMarks = useCallback(next => { setMarks(next); if (key) local.set(`pdf.marks.${key}`, next.length ? next : null); }, [key]);

  // Fit width follows the available width (the docked chat, the window).
  useEffect(() => {
    if (!doc || !fitWidth) return undefined;
    let first = null;
    const fit = () => {
      if (!first || !scroller.current) return;
      // A wide pane would blow a page up to 300 %; past a comfortable reading width the page stays centred instead.
      const width = Math.min(scroller.current.clientWidth - 56, 980);
      setScale(Math.max(0.25, Math.min(4, width / first.getViewport({ scale: 1 }).width)));
    };
    void doc.getPage(1).then(result => { first = result; fit(); });
    const observer = new ResizeObserver(fit);
    observer.observe(scroller.current);
    return () => observer.disconnect();
  }, [doc, fitWidth]);

  // A page asked for with pdf.open is shown once the pages exist.
  useEffect(() => {
    if (!doc || !pendingPage.current) return undefined;
    const timer = setTimeout(() => { goTo(pendingPage.current); pendingPage.current = null; }, 120);
    return () => clearTimeout(timer);
    // goTo changes with the page; this runs once per document
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  const goTo = useCallback((number, offset = 0) => {
    const target = clampPage(number, pages);
    const element = pageEls.current.get(target);
    if (element && scroller.current) scroller.current.scrollTo({ top: element.offsetTop - 16 + offset, behavior: Math.abs(target - page) > 3 ? "auto" : "smooth" });
    setPage(target);
  }, [pages, page]);

  const onVisible = useCallback((number, ratio) => {
    visible.current.set(number, ratio);
    let best = 1; let bestRatio = -1;
    for (const [candidate, value] of visible.current) if (value > bestRatio || (value === bestRatio && candidate < best)) { best = candidate; bestRatio = value; }
    if (bestRatio > 0) setPage(best);
  }, []);
  const pageRef = useCallback((number, element) => { if (element) pageEls.current.set(number, element); else pageEls.current.delete(number); }, []);

  const runSearch = useCallback(async (text, jump = true) => {
    setQuery(text);
    if (!doc || !text.trim()) { setSearch({ query: text, hits: [], active: 0, busy: false }); return []; }
    setSearch(current => ({ ...current, busy: true }));
    const hits = searchTexts(await pageTexts(doc), text).map((hit, index) => ({ ...hit, key: `${hit.page}:${index}` }));
    setSearch({ query: text, hits, active: 0, busy: false });
    if (jump && hits.length) goTo(hits[0].page);
    return hits;
  }, [doc, goTo]);

  useEffect(() => {
    if (!doc) return undefined;
    const timer = setTimeout(() => { if (query !== search.query) void runSearch(query); }, 250);
    return () => clearTimeout(timer);
  }, [query, doc, search.query, runSearch]);

  const stepHit = direction => {
    if (!search.hits.length) return;
    const active = (search.active + direction + search.hits.length) % search.hits.length;
    setSearch(current => ({ ...current, active }));
    goTo(search.hits[active].page);
  };

  const zoom = direction => { setFitWidth(false); setScale(current => stepZoom(current, direction)); };

  // The selection Paul makes becomes a highlight candidate (and part of the reported state).
  const readSelection = useCallback(async () => {
    const chosen = window.getSelection();
    const element = chosen?.anchorNode?.parentElement?.closest?.(".nx-pdf-page");
    if (!chosen || chosen.isCollapsed || !element || !doc) { setSelection(null); return; }
    const number = Number(element.dataset.page);
    const viewport = (await doc.getPage(number)).getViewport({ scale });
    const rects = selectionRects(viewport, element, chosen.getRangeAt(0).getClientRects());
    setSelection(rects.length ? { page: number, text: chosen.toString().trim().slice(0, 500), rects } : null);
  }, [doc, scale]);

  const highlightSelection = () => {
    if (!selection) return;
    saveMarks([...marks, { id: `h${Date.now()}`, page: selection.page, rects: selection.rects, text: selection.text, by: "user" }]);
    window.getSelection()?.removeAllRanges();
    setSelection(null);
  };

  // Commands from the bot side.
  useEffect(() => {
    const mine = inbox.filter(entry => entry.app === "pdf");
    if (!mine.length) return;
    const opening = mine.some(entry => entry.action === "pdf.open") || loaded.status === "loading";
    if (!doc && !opening) {
      os.notify({ level: "warning", message: "The model asked the PDF app to act, but no PDF is open." });
      os.drain("pdf", mine.at(-1).seq);
      return;
    }
    const waiting = !doc && mine.some(entry => entry.action !== "pdf.open");
    for (const { action, payload } of mine) {
      if (action === "pdf.open") {
        pendingPage.current = payload.page || null;
        if (!source || payload.source !== source.value) setSource({ value: payload.source });
        else if (payload.page) goTo(payload.page);
      }
      else if (!doc) continue;
      else if (action === "pdf.goto") goTo(payload.page);
      else if (action === "pdf.zoom") { if (payload.scale === "fit-width") setFitWidth(true); else { setFitWidth(false); setScale(Number(payload.scale)); } }
      else if (action === "pdf.search") void runSearch(payload.query);
      else if (action === "pdf.highlight") {
        void pageTexts(doc).then(texts => {
          const rects = Array.isArray(payload.rects) ? payload.rects : rectsForText(texts, payload.page, payload.text);
          if (!rects.length) { os.notify({ level: "warning", message: `The model's highlight wasn't found on page ${payload.page}: “${payload.text}”` }); return; }
          setMarks(current => { const next = [...current, { id: `m${Date.now()}`, page: payload.page, rects, text: payload.text || "", note: payload.note || "", by: "model", anchor: Array.isArray(payload.rects) ? "rects" : "text" }]; if (key) local.set(`pdf.marks.${key}`, next); return next; });
          goTo(payload.page);
        });
      }
    }
    // Commands that need an open document wait for it.
    if (!waiting) os.drain("pdf", mine.at(-1).seq);
    else {
      // A dependent command must retain the same inbox while loading. Draining
      // zero consumes nothing but publishes a fresh array, retriggering this
      // effect indefinitely before the document can finish opening.
      const opened = mine.filter(entry => entry.action === "pdf.open");
      if (opened.length) os.drain("pdf", Math.max(...opened.map(entry => entry.seq)));
    }
  }, [inbox, doc, source, goTo, runSearch, key, loaded.status]);

  // What the user side shows, for the bot side.
  useEffect(() => () => reportAppState("pdf", { status: "closed", renderedPages: {} }), []);
  useEffect(() => {
    const report = () => reportAppState("pdf", {
      status: loaded.status, source: source?.file ? `upload:${source.file.name}` : source?.value || null, name: loaded.name || null,
      pages, page, scale: Math.round(scale * 100) / 100, fitWidth,
      search: { query: search.query, hits: search.hits.length, active: search.hits.length ? search.active + 1 : 0 },
      selection: selection ? { page: selection.page, text: selection.text } : null,
      highlights: marks.map(({ id, page: at, text, note, by, rects }) => ({ id, page: at, text, note, by, rects })),
      renderedPages: Object.fromEntries(Object.entries(renderedPages).map(([at, rendered]) => {
        const element = pageEls.current.get(Number(at)), pane = scroller.current;
        const box = element?.getBoundingClientRect(), clip = pane?.getBoundingClientRect();
        let visible = false;
        if (box && clip) {
          const left = Math.max(0, box.left, clip.left), right = Math.min(innerWidth, box.right, clip.right);
          const top = Math.max(0, box.top, clip.top), bottom = Math.min(innerHeight, box.bottom, clip.bottom);
          const hit = right > left && bottom > top ? document.elementFromPoint((left + right) / 2, (top + bottom) / 2) : null;
          visible = Boolean(hit?.closest('.nx-pdf')) && !document.querySelector('.nx-onb-scrim');
        }
        return [at, { ...rendered, visible }];
      })),
      error: loaded.error || null,
    });
    report();
    const heartbeat = setInterval(report, 700);
    return () => clearInterval(heartbeat);
  }, [loaded.status, loaded.name, loaded.error, source, pages, page, scale, fitWidth, search, selection, marks, renderedPages]);

  const hitsByPage = useMemo(() => {
    const map = new Map();
    for (const hit of search.hits) { if (!map.has(hit.page)) map.set(hit.page, []); map.get(hit.page).push(hit); }
    return map;
  }, [search.hits]);
  const activeKey = search.hits[search.active]?.key;

  const onKeyDown = event => {
    if (event.target.closest("input")) return;
    if (event.key === "PageDown" || event.key === "ArrowRight") { event.preventDefault(); goTo(page + 1); }
    else if (event.key === "PageUp" || event.key === "ArrowLeft") { event.preventDefault(); goTo(page - 1); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") { event.preventDefault(); searchRef.current?.focus(); }
    else if (event.key === "h" && selection) highlightSelection();
  };
  const openFile = file => { if (file && (file.type === "application/pdf" || /\.pdf$/i.test(file.name))) setSource({ file, value: `upload:${file.name}` }); };
  const noMarks = [];

  return (
    <div className="nx-pdf" onKeyDown={onKeyDown}>
      <NxPdfToolbar name={loaded.name} page={page} pages={pages} scale={scale} fitWidth={fitWidth}
        onOpen={() => picker.current?.click()} onGo={goTo} onZoom={zoom} onFit={() => setFitWidth(true)}
        query={query} onQuery={setQuery} hits={search.hits.length} activeHit={search.active} onStepHit={stepHit} searching={search.busy}
        searchRef={searchRef} canHighlight={Boolean(selection)} onHighlight={highlightSelection}
        marks={marks.length} marksOpen={marksOpen} onToggleMarks={() => setMarksOpen(!marksOpen)} />
      <input ref={picker} type="file" accept="application/pdf,.pdf" hidden onChange={event => { openFile(event.target.files?.[0]); event.target.value = ""; }} />
      <div className="nx-pdf-body">
        <div ref={scroller} className={`nx-pdf-scroll nx-scroll${dragging ? " is-drop" : ""}`} tabIndex={0} aria-label="PDF pages"
          {...(loaded.status === "ready" ? { "data-nx-comment-target": `pdf:${(source?.file ? `upload:${source.file.name}` : String(source?.value || loaded.name)).replace(/\\/g, "/")}`, "data-nx-comment-kind": "pdf", "data-nx-comment-label": loaded.name } : {})}
          onMouseUp={() => void readSelection()} onKeyUp={event => { if (event.shiftKey) void readSelection(); }}
          onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
          onDrop={event => { event.preventDefault(); setDragging(false); openFile(event.dataTransfer.files?.[0]); }}>
          {loaded.status === "ready" ? Array.from({ length: pages }, (_, index) => (
            <NxPdfPage key={`${key}:${index + 1}`} doc={doc} pdfjs={pdfjs} number={index + 1} scale={scale} query={search.query}
              hits={hitsByPage.get(index + 1) || noMarks} activeHit={activeKey} highlights={marks.filter(mark => mark.page === index + 1)}
              onVisible={onVisible} pageRef={pageRef} onRendered={onRendered} />
          )) : (
            <div className="nx-pdf-empty">
              {loaded.status === "loading" ? <><span className="nx-pdf-ghost" aria-hidden="true"><i /><i /><i /><i /><i /></span><strong role="status">Opening {loaded.name}…</strong></> : loaded.status === "error" ? (
                <>
                  <Icon as={FileText} size={26} />
                  <strong>This PDF didn't open</strong>
                  <p>{loaded.error}</p>
                  <span className="nx-pdf-error-actions">
                    {source && !source.file ? <Button variant="primary" size="sm" onClick={() => setSource({ ...source })}>Try again</Button> : null}
                    <Button variant="outline" size="sm" onClick={() => picker.current?.click()}>Choose another PDF</Button>
                  </span>
                </>
              ) : (
                <div className="nx-pdf-welcome">
                  <span className="nx-pdf-stack" aria-hidden="true"><i /><i /><i><b /><b /><b /><b /><b /></i></span>
                  <strong>Put a PDF on the desk</strong>
                  <p>Drop one anywhere here or pick one. Read, search and highlight; a model can open it too, turn to a page and mark what matters.</p>
                  <Button size="sm" variant="primary" icon={FileText} onClick={() => picker.current?.click()}>Choose a PDF</Button>
                  {recent.length ? (
                    <ul className="nx-pdf-recent" aria-label="Recent PDFs">
                      {recent.map(row => (
                        <li key={row.value}><button type="button" onClick={() => setSource({ value: row.value })} title={row.value}>
                          <span className="nx-pdf-recent-page" aria-hidden="true" /><span><strong>{row.name}</strong><small>{row.pages ? `${row.pages} pages` : "PDF"}</small></span>
                        </button></li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              )}
            </div>
          )}
        </div>
        {marksOpen ? (
          <aside className="nx-pdf-marks-list nx-scroll" aria-label="Highlights">
            <strong>Highlights</strong>
            {marks.length ? marks.map(mark => (
              <div key={mark.id} className={`nx-pdf-markrow is-${mark.by}`}>
                <button type="button" onClick={() => goTo(mark.page)}><span>p.{mark.page}{mark.by === "model" ? " · model" : ""}</span>{mark.note || mark.text || "Highlight"}</button>
                <button type="button" aria-label="Remove highlight" title="Remove" onClick={() => saveMarks(marks.filter(other => other.id !== mark.id))}><Icon as={Trash2} size={13} /></button>
              </div>
            )) : <p>Select text on a page, then Highlight (or press H).</p>}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
