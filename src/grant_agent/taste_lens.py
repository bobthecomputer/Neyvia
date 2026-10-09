"""Rendered taste awareness for Neyvia Native.

A skill describes good design in words. The lens looks at what was actually
rendered: it opens a page at desktop and phone widths, measures what a person
meets first (colliding text, overflow, contrast, type and colour discipline,
target sizes, competing primary actions, box clutter) and returns findings
with evidence plus screenshots the model can inspect before it claims visual
work is done. An optional Laya journey exercises the controls the user's goal
depends on and reports what was actually tested.

Measurements inform judgment; they never certify beauty.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TASTE_LENS_SCHEMA = "neyvia.taste_lens.v1"
VIEWPORTS: dict[str, tuple[int, int]] = {"desktop": (1440, 900), "phone": (390, 844)}
LAYA_BASE_URL = "http://127.0.0.1:8793"
MAX_LAYA_RESPONSE_BYTES = 2_000_000

TASTE_CONTRACT = (
    "\n\nNeyvia taste contract (anything visual you create or change): name the primary object and let it "
    "win the first glance. Use one accent with a job (the action, focus, or live state); status colours only "
    "for status. Group with tone and spacing before lines and boxes. Keep one typeface family, a short type "
    "scale, and readable contrast (4.5:1 for text). Use motion only to show arrival, liveness, or settling, "
    "and honour reduced motion. Keep ordinary controls familiar; spend novelty where the product differs. "
    "Before you call visual work done, state the user's goal and the main task flow in plain words. "
    "Pass that goal to preview.taste on the rendered page, look at its desktop and phone "
    "screenshots with neyvia_view_image, fix every blocking finding, and report remaining warnings with their "
    "evidence. When the user's goal depends on controls, pass a journey so Laya exercises them instead of "
    "only looking. Inspect whether the rendered flow actually serves the goal, including an empty and error state. "
    "The lens measures; it never certifies beauty or understands intent on its own, and passing it never replaces looking."
)

# Runs inside the rendered page. Pure measurement: no clicks, no mutation.
PROBE_SCRIPT = r"""
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const limit = (list, count = 8) => list.slice(0, count);
  const parse = value => {
    if (!value) return null;
    let match = value.match(/rgba?\(([^)]+)\)/);
    if (match) {
      const parts = match[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
      return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
    }
    match = value.match(/color\(srgb\s+([^)]+)\)/);
    if (match) {
      const parts = match[1].split(/[\s\/]+/).filter(Boolean).map(Number);
      return [parts[0] * 255, parts[1] * 255, parts[2] * 255, parts.length > 3 ? parts[3] : 1];
    }
    return null;
  };
  const channel = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const luminance = c => 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2]);
  const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const blend = (top, bottom) => { const a = top[3]; return [top[0] * a + bottom[0] * (1 - a), top[1] * a + bottom[1] * (1 - a), top[2] * a + bottom[2] * (1 - a), 1]; };
  const hsl = c => {
    const r = c[0] / 255, g = c[1] / 255, b = c[2] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    let h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  };
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const describe = el => {
    if (!el) return '';
    const cls = String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    const text = (el.getAttribute && (el.getAttribute('aria-label') || '')) || (el.textContent || '').trim();
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (cls ? '.' + cls : '') + (text ? ' "' + text.replace(/\s+/g, ' ').slice(0, 40) + '"' : '');
  };
  const box = el => { const r = el.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const shown = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (r.bottom < 0 || r.top > vh * 1.5 || r.right < 0 || r.left > vw + 400) return false;
    // Closed <details> content and skipped content-visibility subtrees are not on screen.
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })) return false;
    if (el.closest('details:not([open]) > :not(summary)')) return false;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) < 0.05) return false;
    }
    return true;
  };
  // Text past an overflow edge (ellipsis, scroll panes) is not visible there.
  const clipCache = new Map();
  const clipOf = el => {
    if (clipCache.has(el)) return clipCache.get(el);
    let clip = { left: -1e9, top: -1e9, right: 1e9, bottom: 1e9 };
    for (let node = el; node && node.nodeType === 1 && node !== document.documentElement; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
        const b = node.getBoundingClientRect();
        clip = { left: Math.max(clip.left, b.left), top: Math.max(clip.top, b.top), right: Math.min(clip.right, b.right), bottom: Math.min(clip.bottom, b.bottom) };
      }
    }
    clipCache.set(el, clip);
    return clip;
  };
  const backgroundOf = el => {
    const layers = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.backgroundImage && s.backgroundImage !== 'none' && !/^linear-gradient\(rgba?\(0, 0, 0, 0\)/.test(s.backgroundImage)) return null;
      const c = parse(s.backgroundColor);
      if (c && c[3] > 0.02) { layers.push(c); if (c[3] >= 0.98) break; }
    }
    let base = [255, 255, 255, 1];
    const last = layers[layers.length - 1];
    if (!last || last[3] < 0.98) {
      const root = parse(getComputedStyle(document.documentElement).backgroundColor) || parse(getComputedStyle(document.body).backgroundColor);
      if (root && root[3] > 0.5) base = [root[0], root[1], root[2], 1];
    }
    for (let i = layers.length - 1; i >= 0; i--) base = blend(layers[i], base);
    return base;
  };

  const out = { viewport: { width: vw, height: vh }, title: document.title,
    neyviaStartupVisible: Boolean(document.querySelector('#neyvia-startup')) };

  // Overflow
  const scrollWidth = document.documentElement.scrollWidth;
  out.horizontalOverflowPx = Math.max(0, scrollWidth - vw);
  if (out.horizontalOverflowPx > 1) {
    const wide = [...document.body.querySelectorAll('*')].filter(el => { const r = el.getBoundingClientRect(); return r.right > vw + 1 && r.width > 0 && getComputedStyle(el).position !== 'fixed'; })
      .sort((a, b) => b.getBoundingClientRect().right - a.getBoundingClientRect().right);
    out.overflowOffenders = limit(wide, 5).map(el => ({ el: describe(el), box: box(el) }));
  }

  // Text nodes in and near the first viewport
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: node => node.textContent.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const textEls = [], textRuns = [], seen = new Set();
  let node;
  while ((node = walker.nextNode()) && textRuns.length < 900) {
    const el = node.parentElement;
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(el.tagName) || !shown(el)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const clip = clipOf(el);
    const rects = [...range.getClientRects()]
      .map(r => { const left = Math.max(r.left, clip.left), top = Math.max(r.top, clip.top), right = Math.min(r.right, clip.right), bottom = Math.min(r.bottom, clip.bottom); return { left, top, right, bottom, width: right - left, height: bottom - top }; })
      .filter(r => r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < vh);
    rects.slice(0, 3).forEach(r => textRuns.push({ el, r }));
    if (!seen.has(el)) { seen.add(el); textEls.push(el); }
  }

  // Colliding text: two runs overlap and the lower one is not covered by an opaque layer.
  const collisions = [];
  const contains = (a, b) => a === b || a.contains(b) || b.contains(a);
  for (let i = 0; i < textRuns.length && collisions.length < 12; i++) {
    for (let j = i + 1; j < textRuns.length; j++) {
      const a = textRuns[i], b = textRuns[j];
      if (contains(a.el, b.el)) continue;
      const x = Math.max(a.r.left, b.r.left), y = Math.max(a.r.top, b.r.top);
      const w = Math.min(a.r.right, b.r.right) - x, h = Math.min(a.r.bottom, b.r.bottom) - y;
      if (w < 3 || h < 3 || w * h < 16) continue;
      const top = document.elementFromPoint(x + w / 2, y + h / 2);
      if (!top) continue;
      const upper = a.el.contains(top) || a.el === top ? a.el : b.el.contains(top) || b.el === top ? b.el : null;
      if (!upper) continue;
      const lower = upper === a.el ? b.el : a.el;
      let covered = false;
      for (let n = top; n && !n.contains(lower); n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c[3] > 0.9) { covered = true; break; }
      }
      if (!covered) collisions.push({ a: describe(a.el), b: describe(b.el), at: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)] });
      if (collisions.length >= 12) break;
    }
  }
  out.textCollisions = collisions;

  // Contrast, type, and size discipline
  const lowContrast = [], families = {}, sizes = {}, tiny = [];
  let measuredText = 0, unmeasuredText = 0;
  for (const el of textEls) {
    const s = getComputedStyle(el);
    const family = s.fontFamily.split(',')[0].trim().replace(/["']/g, '');
    families[family] = (families[family] || 0) + 1;
    const size = Math.round(parseFloat(s.fontSize) * 2) / 2;
    if (size < 1) continue; // visually hidden label: accessible name only
    sizes[size] = (sizes[size] || 0) + 1;
    const rect = el.getBoundingClientRect();
    if (size < 11 && rect.top < vh && !el.closest('[aria-hidden="true"]')) tiny.push({ el: describe(el), size });
    const fg = parse(s.color);
    if (!fg || fg[3] < 0.05) { unmeasuredText++; continue; }
    const bg = backgroundOf(el);
    if (!bg) { unmeasuredText++; continue; }
    measuredText++;
    const ratio = contrast(blend(fg, bg), bg);
    const weight = parseInt(s.fontWeight, 10) || 400;
    const large = size >= 24 || (size >= 18.5 && weight >= 700);
    const needed = large ? 3 : 4.5;
    if (ratio < needed && rect.top < vh * 1.5 && !el.closest('[disabled], [aria-disabled="true"]')) {
      lowContrast.push({ el: describe(el), ratio: Math.round(ratio * 100) / 100, needed, color: hex(fg), background: hex(bg), size });
    }
  }
  lowContrast.sort((a, b) => a.ratio - b.ratio);
  out.contrast = { measured: measuredText, unmeasured: unmeasuredText, failing: lowContrast.length, worst: limit(lowContrast) };
  out.typefaces = Object.entries(families).sort((a, b) => b[1] - a[1]).map(([family, count]) => ({ family, count }));
  out.fontSizes = Object.keys(sizes).map(Number).sort((a, b) => a - b);
  out.tinyText = { count: tiny.length, examples: limit(tiny, 6) };

  // First-glance candidates: the largest visible type in the first viewport.
  out.firstGlance = textEls.filter(el => el.getBoundingClientRect().top < vh)
    .map(el => ({ el, size: parseFloat(getComputedStyle(el).fontSize), weight: parseInt(getComputedStyle(el).fontWeight, 10) || 400 }))
    .sort((a, b) => (b.size * b.weight) - (a.size * a.weight)).slice(0, 3)
    .map(item => ({ el: describe(item.el), size: item.size, weight: item.weight, box: box(item.el) }));

  // Colour discipline, boxes, geometry
  const hues = {}, radii = new Set();
  let bordered = 0, outlineRings = 0;
  const all = [...document.body.querySelectorAll('*')].slice(0, 5000);
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) < 0.05) continue;
    const colors = [];
    if (textEls.includes(el)) colors.push(parse(s.color));
    colors.push(parse(s.backgroundColor));
    const borderWidth = parseFloat(s.borderTopWidth) + parseFloat(s.borderRightWidth) + parseFloat(s.borderBottomWidth) + parseFloat(s.borderLeftWidth);
    if (borderWidth > 0) colors.push(parse(s.borderTopColor));
    for (const c of colors) {
      if (!c || c[3] < 0.4) continue;
      const [h, sat, light] = hsl(c);
      if (sat < 0.35 || light < 0.22 || light > 0.86) continue;
      const bucket = Math.round(h / 30) % 12;
      hues[bucket] = hues[bucket] || { hue: bucket * 30, count: 0, sample: hex(c) };
      hues[bucket].count++;
    }
    if (r.width * r.height >= 1600) {
      const borderColor = parse(s.borderTopColor);
      if (borderWidth >= 1 && borderColor && borderColor[3] >= 0.12) bordered++;
      if (/(?:^|,)\s*(?:inset\s+)?(?:rgba?\([^)]*\)\s+)?0px 0px 0px 1px/.test(s.boxShadow) || /0px 0px 0px 1px/.test(s.boxShadow)) outlineRings++;
    }
    const radius = parseFloat(s.borderTopLeftRadius);
    if (radius >= 2 && radius < 999 && (parse(s.backgroundColor)?.[3] > 0.05 || borderWidth > 0)) radii.add(Math.round(radius));
  }
  out.accentHues = Object.values(hues).filter(h => h.count >= 2).sort((a, b) => b.count - a.count);
  out.boxes = { bordered, outlineRings };
  out.radii = [...radii].sort((a, b) => a - b);

  // Controls: names, targets, competing primaries
  const controls = [...document.querySelectorAll('a[href], button, [role="button"], input:not([type="hidden"]), select, textarea, summary, [tabindex]:not([tabindex="-1"])')].filter(shown);
  const firstViewport = controls.filter(el => el.getBoundingClientRect().top < vh);
  const unnamed = [], small = [], primaries = [];
  for (const el of controls) {
    const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || el.value || el.getAttribute('placeholder') || '').trim()
      || (el.getAttribute('aria-labelledby') ? 'labelled' : '') || (el.querySelector('img[alt]')?.getAttribute('alt') || '').trim()
      || (el.id && document.querySelector('label[for="' + el.id + '"]') ? 'label' : '') || (el.closest('label') ? 'label' : '');
    if (!name && el.tagName !== 'TEXTAREA') unnamed.push({ el: describe(el), box: box(el) });
    const r = el.getBoundingClientRect();
    if (Math.min(r.width, r.height) < 24 && !['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) small.push({ el: describe(el), size: [Math.round(r.width), Math.round(r.height)] });
  }
  for (const el of firstViewport) {
    if (!['BUTTON', 'A'].includes(el.tagName) && el.getAttribute('role') !== 'button') continue;
    const s = getComputedStyle(el);
    let fill = parse(s.backgroundColor);
    if ((!fill || fill[3] < 0.6) && /gradient/.test(s.backgroundImage)) {
      const stop = (s.backgroundImage.match(/rgba?\([^)]+\)/g) || []).map(parse).filter(Boolean).pop();
      fill = stop || fill;
    }
    if (!fill || fill[3] < 0.6) continue;
    const [, sat, light] = hsl(fill);
    if (sat > 0.35 && light > 0.2 && light < 0.8 && el.getBoundingClientRect().width >= 28) primaries.push(describe(el));
  }
  out.controls = { visible: controls.length, firstViewport: firstViewport.length, unnamed: limit(unnamed), unnamedCount: unnamed.length, smallTargets: limit(small), smallTargetCount: small.length, filledPrimaries: primaries };
  out.images = { missingAlt: [...document.querySelectorAll('img:not([alt])')].filter(shown).length };
  out.headings = { h1: [...document.querySelectorAll('h1')].filter(shown).length, total: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(shown).length };
  out.truncated = [...document.querySelectorAll('*')].slice(0, 4000).filter(el => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow === 'ellipsis' && shown(el)).length;
  return out;
}
"""


def _finding(findings: list[dict[str, Any]], severity: str, rule: str, viewport: str, title: str, evidence: Any, fix: str) -> None:
    findings.append({"severity": severity, "rule": rule, "viewport": viewport, "title": title, "evidence": evidence, "fix": fix})


def evaluate(measurements: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Turn rendered measurements into findings a model can act on."""

    findings: list[dict[str, Any]] = []
    for viewport, m in measurements.items():
        if m.get("error"):
            _finding(findings, "block", "render", viewport, "The page did not render for measurement", m["error"], "Open the page yourself, fix the load failure, then review again.")
            continue
        if m.get("neyviaStartupVisible"):
            _finding(findings, "block", "startup", viewport, "Neyvia did not open the requested page",
                     {"title": m.get("title")}, "Review a running page after its startup view has disappeared.")
            continue
        overflow = int(m.get("horizontalOverflowPx") or 0)
        if overflow > 1:
            _finding(findings, "block", "overflow", viewport, f"Content is {overflow}px wider than the screen", m.get("overflowOffenders") or [],
                     "Let the widest element shrink or wrap (min-width: 0, flexible tracks, wrapping text) instead of hiding overflow.")
        collisions = m.get("textCollisions") or []
        if collisions:
            _finding(findings, "block", "collision", viewport, f"{len(collisions)} places where text overlaps other text", collisions[:6],
                     "Give each label its own space: allow wrapping, drop the less important label at this width, or restack the row.")
        contrast = m.get("contrast") or {}
        if contrast.get("failing"):
            worst = (contrast.get("worst") or [{}])[0]
            severity = "block" if contrast["failing"] >= 6 or float(worst.get("ratio") or 9) < 3 else "warn"
            _finding(findings, severity, "contrast", viewport, f"{contrast['failing']} text elements miss their contrast target", contrast.get("worst") or [],
                     "Raise the text tone (or deepen its background) until body text reaches 4.5:1 and large text 3:1.")
        unnamed = int(((m.get("controls") or {}).get("unnamedCount")) or 0)
        if unnamed:
            _finding(findings, "warn", "names", viewport, f"{unnamed} controls have no accessible name", (m.get("controls") or {}).get("unnamed") or [],
                     "Give icon-only controls an aria-label that says what they do.")
        typefaces = [row for row in (m.get("typefaces") or []) if row.get("count", 0) >= 2]
        if len(typefaces) > 2:
            _finding(findings, "warn", "typeface", viewport, f"{len(typefaces)} typefaces share the page", typefaces[:5],
                     "Use one family for the interface (plus one monospace for code) and express hierarchy with size and weight.")
        tiny = (m.get("tinyText") or {}).get("count", 0)
        if tiny > 3:
            _finding(findings, "warn", "tiny-text", viewport, f"{tiny} labels are smaller than 11px", (m.get("tinyText") or {}).get("examples") or [],
                     "Remove the words that do not earn their place before shrinking the rest; keep reading text at 12px or more.")
        hues = m.get("accentHues") or []
        if len(hues) >= 4:
            _finding(findings, "warn", "colour", viewport, f"{len(hues)} saturated hue families compete", hues[:6],
                     "Keep one accent for action, focus, and live state; reserve other hues for status that means something.")
        primaries = (m.get("controls") or {}).get("filledPrimaries") or []
        if len(primaries) > 2:
            _finding(findings, "warn", "primary", viewport, f"{len(primaries)} filled accent buttons compete in the first view", primaries[:6],
                     "Keep one filled primary action per view; make the others quiet (tonal or text) buttons.")
        small = int(((m.get("controls") or {}).get("smallTargetCount")) or 0)
        if small and viewport == "phone":
            _finding(findings, "warn", "targets", viewport, f"{small} tap targets are under 24px", (m.get("controls") or {}).get("smallTargets") or [],
                     "Grow the hit area to at least 24px (ideally 32-44px on touch) without growing the visual mark.")
        boxes = m.get("boxes") or {}
        drawn = int(boxes.get("bordered") or 0) + int(boxes.get("outlineRings") or 0)
        if drawn > 24:
            _finding(findings, "note", "boxes", viewport, f"{drawn} outlined boxes in the first view", boxes,
                     "Group with tone and spacing; keep lines only where they separate things proximity cannot.")
        radii = m.get("radii") or []
        if len(radii) > 7:
            _finding(findings, "note", "geometry", viewport, f"{len(radii)} different corner radii", radii,
                     "Settle on a short radius scale (for example 8 / 12 / 16 / pill) so nested shapes feel related.")
        sizes = m.get("fontSizes") or []
        if len(sizes) > 11:
            _finding(findings, "note", "type-scale", viewport, f"{len(sizes)} font sizes in use", sizes,
                     "Collapse near-duplicate sizes into a short scale.")
        headings = m.get("headings") or {}
        if int(headings.get("h1") or 0) > 1:
            _finding(findings, "note", "headings", viewport, f"{headings['h1']} top-level headings", headings,
                     "Keep one h1 for the page's primary object.")
        missing_alt = int((m.get("images") or {}).get("missingAlt") or 0)
        if missing_alt:
            _finding(findings, "warn", "alt", viewport, f"{missing_alt} images lack alt text", missing_alt,
                     "Describe meaningful images; give decorative ones alt=\"\".")

    weights = {"block": 18, "warn": 6, "note": 2}
    score = max(0, 100 - sum(weights.get(item["severity"], 0) for item in findings))
    blocking = [item for item in findings if item["severity"] == "block"]
    order = {"block": 0, "warn": 1, "note": 2}
    findings.sort(key=lambda item: (order.get(item["severity"], 3), item["viewport"], item["rule"]))
    return {
        "gate": "blocked" if blocking else "clear",
        "score": score,
        "counts": {level: sum(1 for item in findings if item["severity"] == level) for level in ("block", "warn", "note")},
        "findings": findings,
        "firstGlance": {viewport: m.get("firstGlance") for viewport, m in measurements.items() if isinstance(m, dict)},
        "boundary": "Deterministic measurements of the rendered page at the listed widths. They catch defects "
                    "and discipline problems; they do not judge beauty, brand fit, or whether the page serves the goal.",
    }


def laya_journey_manifest(url: str, goal: str, journey: dict[str, Any]) -> dict[str, Any]:
    """Translate a Native journey into Laya's browser developer-journey manifest."""

    expect = list(journey.get("expect") or [])[:12]
    actions = []
    for step in list(journey.get("actions") or [])[:12]:
        if not isinstance(step, dict) or not str(step.get("label") or "").strip():
            raise ValueError("Each journey action needs a visible control label.")
        kind = str(step.get("kind") or "click").strip().lower()
        if kind not in {"click", "fill", "select", "press"}:
            raise ValueError(f"Unsupported journey action: {kind}")
        # Laya only runs bounded actions that declare the outcome they produce.
        outcome = list(step.get("expect") or [])[:6] or expect[:6]
        if not outcome:
            raise ValueError(f"Journey action '{step['label']}' needs an expected outcome (its own expect, or the journey's expect).")
        action = {
            "kind": kind,
            "label": str(step["label"]).strip()[:160],
            "side_effect": "reversible",
            "expectations": outcome,
        }
        if kind in {"fill", "select", "press"}:
            action["value"] = str(step.get("value") or "")[:2000]
        actions.append(action)
    ready = list(journey.get("ready") or [])[:6]
    for expectation in [*expect, *ready, *(e for a in actions for e in a["expectations"])]:
        if not isinstance(expectation, dict) or not str(expectation.get("kind") or "").strip():
            raise ValueError("Expectations need a kind, for example selector_text or text_present.")
    return {
        "url": str(journey.get("url") or url),
        "goal": goal[:600],
        "required_actions": actions,
        "ready_expectations": ready or [{"kind": "url_contains", "value": urllib.parse.urlparse(str(journey.get("url") or url)).path or "/"}],
        "expectations": expect,
        "ready_timeout_ms": 20000,
        "max_steps": max(1, min(len(actions) + 2, 16)),
        "capture_screenshot": True,
    }


def run_laya_journey(manifest: dict[str, Any], *, approved: bool, base_url: str = LAYA_BASE_URL, timeout: int = 180) -> dict[str, Any]:
    """Ask Laya to run the journey. Unavailable or refused runs stay explicit."""

    payload = json.dumps({"manifest": manifest, "approval": bool(approved)}).encode("utf-8")
    request = urllib.request.Request(base_url.rstrip("/") + "/v1/browser/run", data=payload,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback service
            raw = response.read(MAX_LAYA_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(MAX_LAYA_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        return {"status": "laya_unavailable", "passed": False, "executed": False, "detail": f"Laya did not answer: {type(exc).__name__}"}
    if len(raw) > MAX_LAYA_RESPONSE_BYTES:
        return {"status": "laya_response_too_large", "passed": False, "executed": False}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {"status": "laya_malformed", "passed": False, "executed": False}
    receipt = value.get("receipt") if isinstance(value.get("receipt"), dict) else {}
    coverage = receipt.get("control_coverage") if isinstance(receipt.get("control_coverage"), dict) else {}
    return {
        "status": str(value.get("status") or receipt.get("status") or "unknown"),
        "passed": value.get("passed") is True and receipt.get("passed") is True,
        "executed": value.get("execution_performed") is True,
        "policy": (value.get("policy") or {}).get("reason") or (value.get("policy") or {}).get("decision"),
        "steps": receipt.get("steps"),
        "modelCalls": receipt.get("model_calls"),
        "unmet": receipt.get("unmet_expectations") or [],
        "failureCategory": receipt.get("failure_category"),
        "coverage": {
            "visibleNamedControls": coverage.get("discovered_visible_named"),
            "exercised": coverage.get("exercised_named"),
            "untested": list(coverage.get("untested_visible_names") or [])[:20],
        },
        "screenshot": receipt.get("screenshot") or "",
        "error": receipt.get("error") or value.get("error"),
        "receipt": value,
    }


def triage_report(root, report: dict[str, Any], *, system1_fn=None) -> dict[str, Any]:
    """Route the review's findings: blocking and empty reports are deterministic; the grey zone
    (warn/note only) is a routine decision LAYA answers when confident, else the model decides.
    Advisory only: the blocking gate is never relaxed by this answer."""
    from .laya_ledger import record
    findings = report.get("findings") or []
    counts = report.get("counts") or {}
    if report.get("gate") == "blocked" or counts.get("block"):
        record(root, task="taste-review", path="taste.triage", decision="repair_required", outcome="deterministic",
               detail="blocking finding")
        return {"route": "deterministic", "decision": "repair_with_model", "reason": "blocking findings always need a repair"}
    if not findings:
        record(root, task="taste-review", path="taste.triage", decision="clear", outcome="deterministic", detail="no findings")
        return {"route": "deterministic", "decision": "ship_as_is", "reason": "no findings"}
    from .laya_service import triage
    compact = [f"{f.get('severity')}:{f.get('rule')}:{str(f.get('title'))[:60]}" for f in findings[:8]]
    result = triage(root, "taste-review",
                    "A rendered page review found no blocking defect, only the listed warnings and notes. "
                    "Does a model need to repair the page, or can it ship as is?",
                    ["repair_with_model", "ship_as_is"], context={"findings": compact},
                    path="taste.triage", system1_fn=system1_fn)
    if result["route"] == "laya":
        return {"route": "laya", "decision": result["decision"], "confidence": result["confidence"], "reason": "answered by LAYA"}
    return {"route": result["route"], "decision": "repair_with_model", "reason": "LAYA did not answer confidently; the model decides"}
