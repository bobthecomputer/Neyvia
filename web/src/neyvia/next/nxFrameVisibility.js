// Geometry and hit tests from the current document, never from a mount ACK.
export function frameVisibility(element) {
  const hidden = { visible: false, visibleFraction: 0, unobscuredSamples: 0 };
  if (!element?.isConnected || document.visibilityState === 'hidden') return hidden;
  const box = element.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) return hidden;
  let left = Math.max(0, box.left), top = Math.max(0, box.top);
  let right = Math.min(innerWidth, box.right), bottom = Math.min(innerHeight, box.bottom);
  for (let node = element; node; node = node.parentElement) {
    const css = getComputedStyle(node);
    if (node.hidden || css.display === 'none' || css.visibility !== 'visible' || Number(css.opacity) === 0) return hidden;
    if (node !== element) {
      const clip = node.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(css.overflowX)) { left = Math.max(left, clip.left); right = Math.min(right, clip.right); }
      if (/(auto|scroll|hidden|clip)/.test(css.overflowY)) { top = Math.max(top, clip.top); bottom = Math.min(bottom, clip.bottom); }
    }
  }
  const visibleFraction = Math.max(0, right - left) * Math.max(0, bottom - top) / (box.width * box.height);
  const points = [[.5, .5], [.15, .15], [.85, .15], [.15, .85], [.85, .85]];
  const unobscuredSamples = visibleFraction > 0 ? points.filter(([x, y]) => {
    const hit = document.elementFromPoint(left + (right - left) * x, top + (bottom - top) * y);
    return hit === element || element.contains(hit);
  }).length : 0;
  return { visible: visibleFraction >= .95 && unobscuredSamples === points.length,
    visibleFraction, unobscuredSamples, sampledPoints: points.length };
}
