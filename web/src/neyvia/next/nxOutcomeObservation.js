// Fresh measurements of mounted outcomes. No saved fixture can satisfy them.
const shown = element => {
  if (!element) return false;
  const box = element.getBoundingClientRect(), style = getComputedStyle(element);
  return box.width > 0 && box.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
};
const alpha = color => {
  if (!color || color === 'transparent') return 0;
  const numbers = color.match(/[\d.]+/g)?.map(Number) || [];
  return color.startsWith('rgba') || color.includes('/') ? numbers.at(-1) : 1;
};

export function pdfOutcome(element, phrase = '') {
  const canvas = element?.querySelector('canvas'), layer = element?.querySelector('.textLayer');
  let ink = 0, error = null;
  if (canvas?.width && canvas?.height) {
    try {
      // The complete raster is read once; a digest or ready flag says nothing
      // about whether the page actually contains visible marks.
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      for (let at = 0; at < pixels.length; at += 4) {
        if (pixels[at + 3] > 0 && Math.min(pixels[at], pixels[at + 1], pixels[at + 2]) < 240) ink++;
      }
    } catch (reason) { error = String(reason?.message || reason); }
  }
  const text = layer?.textContent || '';
  return { canvasPresent: shown(canvas), width: canvas?.width || 0, height: canvas?.height || 0,
    inkPixels: ink, nonBlank: ink > 0, text, phrasePresent: !!phrase && text.includes(phrase),
    textLayerPresent: shown(layer) && text.trim().length > 0, error };
}

export function shellOutcomes(root, {only=null} = {}) {
  const started = performance.now();
  if (!root) return {panels:[],chips:[],leaks:[],panelsOpaque:false,chipsUnclipped:false,copyClean:false,durationMs:performance.now()-started};
  const styles = new WeakMap(), boxes = new WeakMap();
  const styleOf = element => { if (!styles.has(element)) styles.set(element,getComputedStyle(element)); return styles.get(element); };
  const boxOf = element => { if (!boxes.has(element)) boxes.set(element,element.getBoundingClientRect()); return boxes.get(element); };
  const shown = element => { if (!element) return false; const box=boxOf(element),style=styleOf(element);
    return box.width>0 && box.height>0 && style.display!=='none' && style.visibility!=='hidden'; };
  const wanted = name => !only || only.includes(name);
  const panels = (wanted('panels') ? [...root.querySelectorAll('.nx-surface, .nx-bubble-float, .nx-launcher, .nx-popover, .nx-menu')] : []).filter(shown).map(element => {
    const style = styleOf(element);
    const box = boxOf(element);
    const points = [[.25,.25],[.5,.5],[.75,.25],[.25,.75],[.75,.75]].map(([x,y]) => [box.left + box.width*x, box.top + box.height*y])
      .filter(([x,y]) => x >= 0 && x < innerWidth && y >= 0 && y < innerHeight);
    for (const under of root.querySelectorAll('.nx-widget.is-dragging, .nx-splitter')) {
      if (!shown(under)) continue;
      const other=boxOf(under),left=Math.max(box.left,other.left),right=Math.min(box.right,other.right),top=Math.max(box.top,other.top),bottom=Math.min(box.bottom,other.bottom);
      if(right>left && bottom>top) points.push([(left+right)/2,(top+bottom)/2]);
    }
    const aboveShell = points.length > 0 && points.every(([x,y]) => {
      const hit = document.elementFromPoint(x,y);
      return element.contains(hit) || !!hit?.closest('.nx-surface, .nx-toast, .nx-wbubbles, .nx-popover, .nx-menu, .nx-arrange-bar');
    });
    return { surface: element.className, opaque: alpha(style.backgroundColor) >= .999 && Number(style.opacity) >= .999,
      aboveShell, background: style.backgroundColor, opacity: style.opacity };
  });
  const chips = (wanted('chips') ? [...root.querySelectorAll('.nx-chip, .nx-filter, .nx-pill, .nx-home-chip, .nx-files-place')] : []).filter(shown).map(element => {
    const range = document.createRange(), walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode()) && !node.textContent.trim()) { /* first real label */ }
    let firstGlyphVisible = false;
    if (node) {
      const start = node.textContent.search(/\S/);
      range.setStart(node, start); range.setEnd(node, start + 1);
      const glyph = range.getBoundingClientRect();
      let left = 0, top = 0, right = innerWidth, bottom = innerHeight;
      for (let parent = element; parent && parent !== root.parentElement; parent = parent.parentElement) {
        const style = styleOf(parent), box = boxOf(parent);
        if (/hidden|clip|auto|scroll/.test(style.overflowX)) { left = Math.max(left, box.left); right = Math.min(right, box.right); }
        if (/hidden|clip|auto|scroll/.test(style.overflowY)) { top = Math.max(top, box.top); bottom = Math.min(bottom, box.bottom); }
      }
      firstGlyphVisible = glyph.width > 0 && glyph.left >= left - 1 && glyph.right <= right + 1 && glyph.top >= top - 1 && glyph.bottom <= bottom + 1;
    }
    // Engines may expose an unclipped Range while painting an ellipsis from
    // the centre. Its measured overflowing label must retain a start origin.
    const label = element.querySelector('.nx-chip-label');
    let labelGeometry=null;
    if (label) {
      const style=styleOf(label),canvas=document.createElement('canvas'),context=canvas.getContext('2d');
      context.font=style.font || `${style.fontSize} ${style.fontFamily}`;
      const textWidth=context.measureText(label.textContent).width;
      labelGeometry={clientWidth:label.clientWidth,scrollWidth:label.scrollWidth,textAlign:style.textAlign,textWidth,font:context.font};
      if (Math.max(label.scrollWidth,textWidth)>label.clientWidth+1 && style.textAlign==='center') firstGlyphVisible=false;
    }
    return { label: element.textContent.trim(), scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
      firstGlyphVisible, labelGeometry, unclipped: element.scrollWidth <= element.clientWidth + 1 && firstGlyphVisible };
  });
  const leaks = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while (wanted('copy') && (node = walker.nextNode())) {
    const text = node.textContent.trim();
    if (!/Traceback \(most recent|\b(?:[A-Za-z_]*Error|Exception|DOMException):|(?:%2f|%5c|%3a)[^\s]*|\b(?:tool|window|session|note|mission|receipt|harness|job)_[0-9a-f]{8,}\b|\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b/i.test(text)) continue;
    const element = node.parentElement;
    if (!element || element.closest('pre, code, textarea, [contenteditable=true], .nx-terminal-output') || !shown(element)) continue;
    leaks.push(text.slice(0,200));
  }
  return { panels, chips, leaks, panelsOpaque: panels.length > 0 && panels.every(row => row.opaque && row.aboveShell),
    chipsUnclipped: chips.length > 0 && chips.every(row => row.unclipped), copyClean: wanted('copy') && leaks.length === 0,
    durationMs: performance.now() - started };
}
