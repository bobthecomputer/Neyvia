import { checkProviderRegistry, checkProviderTree, checkProviderSvg } from "./nxProviderMarkContracts.js";
import { PROVIDER_MARKS, resolveProviderMarkId } from "./providerMarksData.js";

/**
 * Turns a registry entry into a small SVG element tree. ProviderMark.jsx renders the tree with
 * React and the preview/test tools serialise it to a string, so both paths share one source.
 * Attribute names are exact SVG names (fill-rule, gradientUnits); nodes are { tag, attrs, children, text }.
 */

const SVG_NS = "http://www.w3.org/2000/svg";
const INK_STROKE_JOIN = { "stroke-linecap": "round", "stroke-linejoin": "round" };

function fallbackLetter(id, title) {
  const source = String(title || id || "").trim();
  const match = source.match(/[\p{L}\p{N}]/u);
  return match ? match[0].toLocaleUpperCase() : "?";
}

function describeGradient(gradient, uid) {
  const attrs = { id: `${uid}-${gradient.id}` };
  const radial = gradient.type === "radial";
  for (const key of radial ? ["cx", "cy", "r", "fx", "fy"] : ["x1", "y1", "x2", "y2"]) if (gradient[key] !== undefined) attrs[key] = gradient[key];
  if (gradient.units) attrs.gradientUnits = gradient.units;
  return {
    tag: radial ? "radialGradient" : "linearGradient",
    attrs,
    children: gradient.stops.map(([offset, color, opacity]) => ({
      tag: "stop",
      attrs: { offset, "stop-color": color, ...(opacity === undefined ? {} : { "stop-opacity": opacity }) },
    })),
  };
}

function describePath(path, { mono, toneFill, uid }) {
  const attrs = { d: path.d };
  if (path.stroke) {
    attrs.fill = "none";
    attrs.stroke = mono || path.fill === undefined ? "currentColor" : path.fill;
    attrs["stroke-width"] = path.stroke;
    Object.assign(attrs, INK_STROKE_JOIN);
    return { tag: "path", attrs };
  }
  let fill = toneFill;
  if (!mono && path.fill) fill = path.fill.replace(/^url\(#([^)]+)\)$/, `url(#${uid}-$1)`);
  attrs.fill = fill;
  if (path.fillRule) attrs["fill-rule"] = path.fillRule;
  if (path.opacity !== undefined && !mono) attrs.opacity = path.opacity;
  return { tag: "path", attrs };
}

/**
 * @param {string} id       registry id or alias; unknown ids get the letter fallback
 * @param {object} options  { mono, size, title, className, uid }
 */
function describeProviderMarkUnchecked(id, { mono = false, size = 16, title, className, uid = "pm" } = {}) {
  const resolved = resolveProviderMarkId(id);
  const entry = resolved ? PROVIDER_MARKS[resolved] : null;
  const classes = ["ny-pmark"];
  const svgAttrs = { xmlns: SVG_NS, width: size, height: size, focusable: "false" };
  if (title) {
    svgAttrs.role = "img";
    svgAttrs["aria-label"] = title;
  } else {
    svgAttrs["aria-hidden"] = "true";
  }

  let viewBox = "0 0 24 24";
  let defs = [];
  let children;

  if (!entry) {
    classes.push("ny-pmark--fallback");
    if (mono) classes.push("ny-pmark--mono");
    children = [
      { tag: "rect", attrs: { class: "ny-pmark__tile", x: 2, y: 2, width: 20, height: 20, rx: 6 } },
      {
        tag: "text",
        attrs: { class: "ny-pmark__letter", x: 12, y: 12, dy: ".35em", "text-anchor": "middle" },
        text: fallbackLetter(id, title),
      },
    ];
  } else {
    const variant = mono && entry.mono ? entry.mono : entry;
    viewBox = variant.viewBox;
    let toneFill = "currentColor";
    if (mono) {
      classes.push("ny-pmark--mono");
    } else if (entry.ink) {
      classes.push("ny-pmark--ink");
    } else if (entry.color) {
      toneFill = entry.color;
    }
    if (!mono && entry.gradients) defs = entry.gradients.map((gradient) => describeGradient(gradient, uid));
    children = variant.paths.map((path) => describePath(path, { mono, toneFill, uid }));
    svgAttrs["data-mark"] = entry.id;
  }

  if (className) classes.push(className);
  svgAttrs.class = classes.join(" ");
  svgAttrs.viewBox = viewBox;
  return {
    tag: "svg",
    attrs: svgAttrs,
    children: defs.length ? [{ tag: "defs", attrs: {}, children: defs }, ...children] : children,
  };
}

const escapeAttr = (value) => String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const escapeText = (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;");

export function serializeSvgNode(node) {
  const attrs = Object.entries(node.attrs || {})
    .map(([key, value]) => ` ${key}="${escapeAttr(value)}"`)
    .join("");
  const inner = node.text !== undefined ? escapeText(node.text) : (node.children || []).map(serializeSvgNode).join("");
  return inner ? `<${node.tag}${attrs}>${inner}</${node.tag}>` : `<${node.tag}${attrs}/>`;
}

let stringCounter = 0;

/** Static SVG markup for a mark: used by the preview page and the tests. */
function providerMarkSvgStringUnchecked(id, options = {}) {
  const uid = options.uid || `pms${(stringCounter += 1)}`;
  return serializeSvgNode(describeProviderMark(id, { ...options, uid }));
}

export function describeProviderMark(id, options = {}) { const resolved = resolveProviderMarkId(id); checkProviderRegistry(PROVIDER_MARKS, Object.keys(PROVIDER_MARKS)); return checkProviderTree(id, options, describeProviderMarkUnchecked(id, options), resolved ? PROVIDER_MARKS[resolved] : null); }
export function providerMarkSvgString(id, options = {}) { const resolved = resolveProviderMarkId(id); return checkProviderSvg(id, options, providerMarkSvgStringUnchecked(id, options), resolved ? PROVIDER_MARKS[resolved] : null); }
