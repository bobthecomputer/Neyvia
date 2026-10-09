// Where a comment sits (plan 29 B). Pure DOM helpers: turn a click, a text
// selection or a dragged region into a stored anchor, and turn a stored anchor
// back into a box on screen. The backend keeps anchors as opaque JSON per
// target (COMMENTS-contract.md); the kinds here are text, dom, pdf, browser,
// image and region. Rects are fractions of the thing they sit on, so a comment
// stays put when the window is resized or a PDF is zoomed.

export const TARGET_ATTR = "data-nx-comment-target"; // an app marks the content of one file/page/url: "notes:C:/n/a.md"
const KIND_ATTR = "data-nx-comment-kind"; // text | pdf | dom | image | browser (default dom)
const LABEL_ATTR = "data-nx-comment-label"; // what the list calls it: "launch.md"

const clamp01 = value => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));
const collapse = value => String(value ?? "").replace(/\s+/g, " ").trim();
export const quoteOf = (value, max = 160) => { const text = collapse(value); return text.length > max ? `${text.slice(0, max - 1)}…` : text; };
export const slashes = value => String(value || "").replace(/\\/g, "/");

// ---- targets ------------------------------------------------------------------------

/** Every target an app marked inside `root`, in document order: [{ id, kind, label, element }]. */
export function targetsIn(root) {
  if (!root) return [];
  return [...root.querySelectorAll(`[${TARGET_ATTR}]`)].map(element => ({
    id: element.getAttribute(TARGET_ATTR), kind: element.getAttribute(KIND_ATTR) || "dom", label: element.getAttribute(LABEL_ATTR) || "", element,
  })).filter(entry => entry.id);
}

/** The nearest marked target around an element, or null. */
export function targetAround(element, root) {
  const found = element?.closest?.(`[${TARGET_ATTR}]`);
  if (!found || (root && !root.contains(found))) return null;
  return { id: found.getAttribute(TARGET_ATTR), kind: found.getAttribute(KIND_ATTR) || "dom", label: found.getAttribute(LABEL_ATTR) || "", element: found };
}

/** What a window's own target is when its app marks none: the window itself. */
export function windowTarget(desc) {
  if (!desc) return { id: "app:neyvia", kind: "pane", targetKind: "app", label: "Neyvia" };
  if (desc.type === "pane") {
    const kind = { preview: "preview", browser: "browser", file: "files", artifact: "artifact", outputs: "artifact" }[desc.kind] || "pane";
    return { id: `pane:${desc.kind}:${slashes(desc.target || "")}`.replace(/:$/, ""), kind: "dom", targetKind: kind, label: desc.kind };
  }
  const targetKind = desc.app === "app-factory" ? "app-factory" : desc.app === "files" ? "files" : desc.app === "notes" ? "notes" : desc.app === "pdf" ? "pdf" : "dom";
  return { id: `app:${desc.app}${desc.target ? `:${slashes(desc.target)}` : ""}`, kind: "dom", targetKind, label: desc.app };
}

/** The contract's targetKind for a marked target (notes:, pdf:, files:, code:, browser:… ids lead with it). */
export function targetKindOf(id, fallback = "dom") {
  const lead = String(id || "").split(":")[0];
  return ["notes", "code", "pdf", "dom", "preview", "browser", "image", "artifact", "files", "pane", "app-factory"].includes(lead) ? lead : fallback;
}

// ---- selectors -----------------------------------------------------------------------

const STABLE_CLASS = /^(?:nx|af|neyvia|pdf|lucide)-[a-z0-9-]+$/i;
const reactId = /^:r|^\d|\d{4,}/;

function segmentOf(element) {
  const tag = element.tagName.toLowerCase();
  const id = element.getAttribute("id");
  if (id && !reactId.test(id) && !/[^\w-]/.test(id)) return `#${id}`;
  for (const attribute of ["data-testid", "data-nx-id", "data-session-id", "data-page"]) {
    const value = element.getAttribute(attribute);
    if (value && !/["\\]/.test(value)) return `${tag}[${attribute}="${value}"]`;
  }
  const label = element.getAttribute("aria-label");
  if (label && label.length < 60 && !/["\\]/.test(label)) return `${tag}[aria-label="${label}"]`;
  const classes = [...element.classList].filter(name => STABLE_CLASS.test(name) && !/^is-/.test(name)).slice(0, 2);
  return `${tag}${classes.map(name => `.${CSS.escape(name)}`).join("")}`;
}

function withNth(element, segment) {
  const parent = element.parentElement;
  if (!parent) return segment;
  let same = 0; let index = 0;
  for (const sibling of parent.children) {
    let matches = false;
    try { matches = sibling.matches(segment); } catch { matches = false; }
    if (matches) { same += 1; if (sibling === element) index = same; }
  }
  return same > 1 ? `${segment}:nth-of-type(${[...parent.children].filter(sibling => sibling.tagName === element.tagName).indexOf(element) + 1})` : segment;
}

/** A selector for `element` that finds it again inside `root`: the shortest unique chain of stable parts. */
export function selectorFor(element, root) {
  const chain = [];
  let node = element;
  while (node && node !== root && node.nodeType === 1) {
    chain.unshift(withNth(node, segmentOf(node)));
    const selector = chain.join(" > ");
    try {
      const hits = root.querySelectorAll(selector);
      if (hits.length === 1 && hits[0] === element) return selector;
    } catch { /* an odd attribute value: keep climbing */ }
    node = node.parentElement;
  }
  return chain.join(" > ");
}

function fromText(root, selector, quote) {
  if (!quote) return null;
  const tag = String(selector).split(/[>\s]/).filter(Boolean).pop()?.match(/^[a-z][a-z0-9]*/i)?.[0] || "*";
  const needle = collapse(quote).slice(0, 60).toLowerCase();
  const candidates = [...root.querySelectorAll(tag)].filter(node => collapse(node.textContent).toLowerCase().includes(needle));
  // The deepest element that still holds the words is the one that was meant.
  return candidates.find(node => !candidates.some(other => other !== node && node.contains(other))) || null;
}

const sameOrigin = frame => { try { return Boolean(frame.contentDocument?.body); } catch { return false; } };

/** The element a stored selector means (inside `root`, or through a same-origin iframe: "a >>> b"), or null. */
export function findElement(root, selector, quote = "") {
  if (!root || !selector) return null;
  const [outer, ...rest] = String(selector).split(" >>> ");
  let found = null;
  try { found = root.querySelector(outer); } catch { found = null; }
  if (!found && !rest.length) found = fromText(root, outer, quote);
  if (found && rest.length) {
    if (found.tagName !== "IFRAME" || !sameOrigin(found)) return found;
    return findElement(found.contentDocument.body, rest.join(" >>> "), quote) || found;
  }
  if (found && quote && !collapse(found.textContent).toLowerCase().includes(collapse(quote).slice(0, 24).toLowerCase())) return fromText(root, outer, quote) || found;
  return found;
}

// ---- boxes (viewport pixels) -----------------------------------------------------------

/** An element's box on screen, looking through iframes' scale (an app preview is scaled to fit). */
export function boxOf(element) {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  let { left, top, width, height } = rect;
  const frame = element.ownerDocument?.defaultView?.frameElement;
  if (frame) {
    const outer = frame.getBoundingClientRect();
    const scaleX = frame.clientWidth ? outer.width / frame.clientWidth : 1;
    const scaleY = frame.clientHeight ? outer.height / frame.clientHeight : 1;
    left = outer.left + left * scaleX; top = outer.top + top * scaleY; width *= scaleX; height *= scaleY;
  }
  return { x: left, y: top, w: width, h: height };
}

const unionOf = rects => {
  const list = [...rects].filter(rect => rect.width > 0 || rect.height > 0);
  if (!list.length) return null;
  const left = Math.min(...list.map(rect => rect.left)); const top = Math.min(...list.map(rect => rect.top));
  const right = Math.max(...list.map(rect => rect.right)); const bottom = Math.max(...list.map(rect => rect.bottom));
  return { x: left, y: top, w: right - left, h: bottom - top };
};

const fractionIn = (box, outer) => ({
  x: clamp01((box.x - outer.x) / (outer.w || 1)), y: clamp01((box.y - outer.y) / (outer.h || 1)),
  width: clamp01(box.w / (outer.w || 1)), height: clamp01(box.h / (outer.h || 1)),
});
const boxFrom = (rect, outer) => ({ x: outer.x + rect.x * outer.w, y: outer.y + rect.y * outer.h, w: Math.max(rect.width * outer.w, 2), h: Math.max(rect.height * outer.h, 2) });

// ---- text in a textarea (Notes source view, code) -----------------------------------------

export function lineOf(value, offset) {
  let line = 1;
  for (let index = 0; index < Math.min(offset, value.length); index += 1) if (value.charCodeAt(index) === 10) line += 1;
  return line;
}
export function offsetOfLine(value, line) {
  let offset = 0;
  for (let current = 1; current < line; current += 1) { const next = value.indexOf("\n", offset); if (next < 0) return value.length; offset = next + 1; }
  return offset;
}

/** An anchor for what is selected (or the caret line) in a textarea. */
export function textAnchor(textarea, path) {
  const value = textarea.value;
  let start = textarea.selectionStart ?? 0; let end = textarea.selectionEnd ?? start;
  if (start === end) { // a click: the whole line the caret is on
    start = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1; if (value[start - 1] !== "\n" && start !== 0) start = 0;
    const next = value.indexOf("\n", end); end = next < 0 ? value.length : next;
  }
  const quote = value.slice(start, end);
  return { kind: "text", path: slashes(path), startLine: lineOf(value, start), endLine: lineOf(value, Math.max(start, end - (quote.endsWith("\n") ? 1 : 0))), quote: quoteOf(quote, 240), range: { start, end } };
}

let mirror = null;
const MIRRORED = ["boxSizing", "width", "fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing", "textTransform", "wordSpacing", "textIndent", "lineHeight",
  "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "tabSize", "whiteSpace", "overflowWrap", "wordBreak"];

/** The y (px from the textarea's content top) where `offset` sits, with wrapping, measured on a hidden twin. */
function caretY(textarea, offset) {
  const style = getComputedStyle(textarea);
  if (!mirror) {
    mirror = document.createElement("div");
    mirror.setAttribute("aria-hidden", "true");
    Object.assign(mirror.style, { position: "fixed", left: "-99999px", top: "0", visibility: "hidden", pointerEvents: "none", overflow: "hidden", height: "auto" });
  }
  if (!mirror.isConnected) document.body.appendChild(mirror);
  for (const name of MIRRORED) mirror.style[name] = style[name];
  mirror.style.whiteSpace = "pre-wrap"; mirror.style.overflowWrap = "break-word";
  mirror.textContent = textarea.value.slice(0, offset);
  const marker = document.createElement("span");
  marker.textContent = "​";
  mirror.appendChild(marker);
  const y = marker.offsetTop;
  const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5;
  return { y, line };
}

/** Where a text anchor's lines are now in a textarea (viewport px), or null if they scrolled out of it. */
function textareaBox(textarea, anchor) {
  const value = textarea.value;
  let start = offsetOfLine(value, anchor.startLine || 1);
  let end = anchor.endLine ? offsetOfLine(value, anchor.endLine + 1) : start;
  const quote = String(anchor.quote || "");
  if (quote) { // the lines moved: find the words again, nearest to where they were
    const first = quote.split("\n")[0];
    if (first && !value.slice(start, end).includes(first)) {
      const at = value.indexOf(quote) >= 0 ? value.indexOf(quote) : value.indexOf(first);
      if (at >= 0) { start = at; end = at + quote.length; }
    }
  }
  const rect = textarea.getBoundingClientRect();
  const style = getComputedStyle(textarea);
  const top = caretY(textarea, start); const bottom = caretY(textarea, Math.max(start, end - 1));
  const padLeft = parseFloat(style.paddingLeft) || 0; const padRight = parseFloat(style.paddingRight) || 0;
  const y = rect.top + (parseFloat(style.borderTopWidth) || 0) + top.y - textarea.scrollTop;
  const h = bottom.y + bottom.line - top.y;
  if (y + h < rect.top || y > rect.bottom) return { hidden: true };
  return { x: rect.left + padLeft, y: Math.max(y, rect.top), w: rect.width - padLeft - padRight, h: Math.min(h, rect.bottom - Math.max(y, rect.top)) };
}

/** The words of a quote in rendered text (a note's preview): a Range's box, or null. */
function renderedTextBox(root, quote) {
  const first = collapse(String(quote || "").split("\n").find(line => collapse(line).length >= 4) || "");
  if (!first) return null;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: node => (node.parentElement?.closest("textarea, .nx-cm-ui, script, style") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT) });
  const needle = first.slice(0, 80).toLowerCase();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = node.textContent.toLowerCase().indexOf(needle);
    if (at < 0) continue;
    const range = document.createRange();
    range.setStart(node, at); range.setEnd(node, Math.min(node.textContent.length, at + first.length));
    return unionOf(range.getClientRects());
  }
  return null;
}

// ---- anchors from a gesture ---------------------------------------------------------------

function pageOf(node) { return node?.closest?.(".nx-pdf-page[data-page]") || null; }

/** An anchor for a text selection (a Range) or null: PDF -> page rect + words, anything else -> the element holding it. */
export function anchorFromRange(range, target) {
  const text = quoteOf(range.toString(), 400);
  if (!text) return null;
  const node = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
  const rects = unionOf(range.getClientRects());
  if (!rects) return null;
  const page = pageOf(node);
  if (page && target.kind === "pdf") {
    const outer = boxOf(page);
    return { anchor: { kind: "pdf", page: Number(page.dataset.page), rect: fractionIn(rects, outer), coordinateSpace: "page-fraction", quote: text }, box: rects };
  }
  const holder = node.closest("p, li, h1, h2, h3, h4, h5, h6, td, th, pre, blockquote, label, button, a, span, div") || node;
  return { anchor: domAnchor(holder, target, { quote: text, box: rects }), box: rects };
}

/** A DOM anchor: a stable selector, the words, and where inside the target's box it sits. */
export function domAnchor(element, target, { quote = "", box = null } = {}) {
  const frame = element.ownerDocument?.defaultView?.frameElement;
  let selector;
  if (frame) selector = `${selectorFor(frame, target.element)} >>> ${selectorFor(element, element.ownerDocument.body)}`;
  else selector = selectorFor(element, target.element);
  const outer = boxOf(target.element); const mine = box || boxOf(element);
  return {
    kind: target.kind === "browser" ? "browser" : "dom", selector, quote: quoteOf(quote || element.innerText || element.getAttribute("aria-label") || element.getAttribute("alt") || ""),
    tag: element.tagName.toLowerCase(), rect: fractionIn(mine, outer), coordinateSpace: "target-fraction",
  };
}

/** A region anchor from a dragged or clicked box (viewport px) over a page, an image or a frame. */
export function regionAnchor(box, target, hit) {
  const page = pageOf(hit);
  if (page && target.kind === "pdf") return { kind: "pdf", page: Number(page.dataset.page), rect: fractionIn(box, boxOf(page)), coordinateSpace: "page-fraction", quote: "" };
  if (target.kind === "browser") { // a page's picture: the box in the page's own viewport, with the address it was on
    const picture = target.element.querySelector("img") || target.element;
    return { kind: "browser", url: String(target.id).replace(/^browser:/, ""), selector: "", rect: fractionIn(box, boxOf(picture)), coordinateSpace: "page-fraction", quote: "" };
  }
  const image = hit?.closest?.("img, canvas, video");
  if (image && (target.kind === "image" || !image.closest("button"))) {
    const outer = boxOf(image);
    const natural = { w: image.naturalWidth || image.width || Math.round(outer.w), h: image.naturalHeight || image.height || Math.round(outer.h) };
    const fraction = fractionIn(box, outer);
    return { kind: "image", selector: selectorFor(image, target.element), rect: { x: Math.round(fraction.x * natural.w), y: Math.round(fraction.y * natural.h), width: Math.round(fraction.width * natural.w), height: Math.round(fraction.height * natural.h) }, coordinateSpace: "image-px", imageWidth: natural.w, imageHeight: natural.h };
  }
  const frame = hit?.closest?.("iframe");
  const base = frame || target.element;
  return { kind: "region", selector: frame ? selectorFor(frame, target.element) : "", rect: fractionIn(box, boxOf(base)), coordinateSpace: frame ? "frame-fraction" : "target-fraction", quote: "" };
}

// ---- anchors back to boxes ---------------------------------------------------------------------

/**
 * Where a stored anchor is on screen now: { x, y, w, h } in viewport px, { hidden: true } when it is
 * scrolled out of its container, or null when it can't be found (the comment stays in the list).
 */
export function locate(anchor, root) {
  if (!anchor || !root) return null;
  switch (anchor.kind) {
    case "text": {
      const areas = [...root.querySelectorAll("textarea")].filter(area => area.offsetParent !== null);
      if (areas.length) return textareaBox(areas[0], anchor);
      return renderedTextBox(root, anchor.quote);
    }
    case "pdf": {
      const page = root.querySelector(`.nx-pdf-page[data-page="${anchor.page}"]`);
      if (!page) return { hidden: true };
      const outer = boxOf(page);
      if (!anchor.rect) return { x: outer.x, y: outer.y, w: outer.w, h: 24 };
      return clipTo(boxFrom(anchor.rect, outer), page.closest(".nx-pdf-scroll, .nx-pdf-pages, [data-pdf-scroll]") || root);
    }
    case "image": {
      const image = (anchor.selector && findElement(root, anchor.selector)) || root.querySelector("img, canvas");
      if (!image) return null;
      const outer = boxOf(image);
      const rect = anchor.rect || { x: 0, y: 0, width: 0, height: 0 };
      const fraction = anchor.coordinateSpace === "image-px" && anchor.imageWidth
        ? { x: rect.x / anchor.imageWidth, y: rect.y / anchor.imageHeight, width: rect.width / anchor.imageWidth, height: rect.height / anchor.imageHeight } : rect;
      return clipTo(boxFrom(fraction, outer), root);
    }
    case "browser": {
      if (anchor.selector) { const element = findElement(root, anchor.selector, anchor.quote); if (element) return clipTo(boxOf(element), root); }
      const picture = root.querySelector("img") || root;
      return anchor.rect ? clipTo(boxFrom(anchor.rect, boxOf(picture)), root) : null;
    }
    case "region": {
      const base = (anchor.selector && findElement(root, anchor.selector)) || root;
      return clipTo(boxFrom(anchor.rect || { x: 0, y: 0, width: 0, height: 0 }, boxOf(base)), root);
    }
    default: {
      const element = findElement(root, anchor.selector, anchor.quote);
      if (element && anchor.quote && anchor.quote.length > 3 && element.tagName !== "IFRAME") {
        const range = rangeBox(element, anchor.quote);
        if (range) return clipTo(range, root);
      }
      if (element) return clipTo(boxOf(element), root);
      if (anchor.rect) return clipTo(boxFrom(anchor.rect, boxOf(root)), root);
      return null;
    }
  }
}

function rangeBox(element, quote) {
  const first = collapse(quote).slice(0, 60).toLowerCase();
  if (!first) return null;
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = node.textContent.toLowerCase().indexOf(first.slice(0, Math.min(first.length, 30)));
    if (at < 0) continue;
    const range = document.createRange();
    range.setStart(node, at); range.setEnd(node, Math.min(node.textContent.length, at + Math.min(first.length, node.textContent.length - at)));
    const box = unionOf(range.getClientRects());
    if (box) return box;
  }
  return null;
}

/** Hidden when the box lies outside the scroll container that holds it. */
function clipTo(box, container) {
  if (!box) return null;
  if (!container?.getBoundingClientRect) return box;
  const outer = container.getBoundingClientRect();
  if (box.y + box.h < outer.top || box.y > outer.bottom || box.x + box.w < outer.left || box.x > outer.right) return { hidden: true };
  return box;
}

// ---- words for a person and for the agent ------------------------------------------------------------

export function anchorLabel(anchor) {
  if (!anchor) return "";
  switch (anchor.kind) {
    case "text": return anchor.endLine && anchor.endLine !== anchor.startLine ? `Lines ${anchor.startLine}–${anchor.endLine}` : `Line ${anchor.startLine ?? 1}`;
    case "pdf": return `Page ${anchor.page}`;
    case "image": return "Image region";
    case "region": return "Region";
    case "browser": return anchor.url ? String(anchor.url).replace(/^https?:\/\//, "").slice(0, 40) : "Page element";
    default: {
      const tail = String(anchor.selector || "").split(" >>> ").pop().split(" > ").pop().replace(/:nth-of-type\(\d+\)/, "");
      return anchor.tag && !tail ? anchor.tag : tail.replace(/\[[^\]]*\]/g, "").replace(/^#/, "#") || "Element";
    }
  }
}

/** What the person selected on this window's page right now, for the pop-out chat's context block. */
export function currentSelection(root) {
  const active = document.activeElement;
  if (active?.tagName === "TEXTAREA" && root?.contains(active) && active.selectionStart !== active.selectionEnd) return quoteOf(active.value.slice(active.selectionStart, active.selectionEnd), 300);
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || !root) return "";
  const node = selection.anchorNode?.nodeType === 1 ? selection.anchorNode : selection.anchorNode?.parentElement;
  return node && root.contains(node) ? quoteOf(selection.toString(), 300) : "";
}
