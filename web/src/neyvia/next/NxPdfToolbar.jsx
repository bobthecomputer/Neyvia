import { useEffect, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, FolderOpen, Highlighter, ListTree, MoveHorizontal, Search, ZoomIn, ZoomOut } from "lucide-react";

import { Icon, IconButton } from "./nxPrimitives.jsx";

// The PDF app's toolbar: open, page, zoom, search, highlight.

function PageField({ page, pages, onGo }) {
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);
  return (
    <label className="nx-pdf-pagefield">
      <input aria-label="Page" inputMode="numeric" value={draft} onChange={event => setDraft(event.target.value.replace(/\D/g, ""))}
        onKeyDown={event => { if (event.key === "Enter") onGo(Number(draft)); }} onBlur={() => setDraft(String(page))} />
      <span>/ {pages || "–"}</span>
    </label>
  );
}

export function NxPdfToolbar({
  name, page, pages, scale, fitWidth, onOpen, onGo, onZoom, onFit, query, onQuery, hits, activeHit, onStepHit,
  searchRef, canHighlight, onHighlight, marks, marksOpen, onToggleMarks, searching,
}) {
  const ready = pages > 0;
  return (
    <div className="nx-pdf-bar" role="toolbar" aria-label="PDF">
      <IconButton icon={FolderOpen} size="sm" label="Open a PDF" onClick={onOpen} />
      <span className="nx-pdf-name" title={name}>{name || "No PDF open"}</span>
      <span className="nx-pdf-sep" />
      <IconButton icon={ChevronLeft} size="sm" label="Previous page" disabled={!ready || page <= 1} onClick={() => onGo(page - 1)} />
      {ready ? <PageField page={page} pages={pages} onGo={onGo} /> : null}
      <IconButton icon={ChevronRight} size="sm" label="Next page" disabled={!ready || page >= pages} onClick={() => onGo(page + 1)} />
      <span className="nx-pdf-sep" />
      <span className="nx-pdf-zoomgroup">
        <IconButton icon={ZoomOut} size="sm" label="Zoom out" disabled={!ready} onClick={() => onZoom(-1)} />
        <span className="nx-pdf-zoom" aria-live="polite">{Math.round(scale * 100)}%</span>
        <IconButton icon={ZoomIn} size="sm" label="Zoom in" disabled={!ready} onClick={() => onZoom(1)} />
      </span>
      <IconButton icon={MoveHorizontal} size="sm" label="Fit width" active={fitWidth} disabled={!ready} onClick={onFit} />
      <span className="nx-pdf-spacer" />
      <label className={`nx-pdf-search${query ? " has-query" : ""}`}>
        <Icon as={Search} size={13} />
        <input ref={searchRef} type="search" placeholder="Search" value={query} disabled={!ready} aria-label="Search in PDF"
          onChange={event => onQuery(event.target.value)}
          onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); onStepHit(event.shiftKey ? -1 : 1); } }} />
        {query ? <span className="nx-pdf-hits" aria-live="polite">{searching ? "…" : hits ? `${activeHit + 1}/${hits}` : "0"}</span> : null}
      </label>
      <span className="nx-pdf-matchnav">
        <IconButton icon={ChevronUp} size="sm" label="Previous match" disabled={!hits} onClick={() => onStepHit(-1)} />
        <IconButton icon={ChevronDown} size="sm" label="Next match" disabled={!hits} onClick={() => onStepHit(1)} />
      </span>
      <span className="nx-pdf-sep is-late" />
      <button type="button" className="nx-btn nx-btn-sm nx-btn-ghost nx-pdf-highlight" aria-label="Highlight" disabled={!canHighlight} onClick={onHighlight} title="Highlight the selected text">
        <Icon as={Highlighter} size={14} /><span className="nx-btn-label">Highlight</span>
      </button>
      <IconButton icon={ListTree} size="sm" label={`Highlights (${marks})`} active={marksOpen} disabled={!ready} onClick={onToggleMarks} />
    </div>
  );
}
