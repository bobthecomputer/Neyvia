import { memo, useEffect, useState } from "react";
import Markdown from "react-markdown";
import { forgetLiveMessage, isLiveMessage } from "./neyviaLiveMessages.js";
import "./NeyviaMessageBody.css";

const components = {
  a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer" onClick={event => event.stopPropagation()}>{children}</a>,
  // A model-authored image URL must not trigger a background request on render.
  img: ({ alt, src }) => src ? <a href={src} target="_blank" rel="noopener noreferrer" onClick={event => event.stopPropagation()}>{alt || "Open image"}</a> : <span>{alt}</span>,
};

const NO_PLUGINS = [];
const FADE_MS = 520;

function prefersReducedMotion() {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  if (document.querySelector?.('[data-neyvia-reduce-motion="true"]')) return true;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Wrap each revealed prose word in a span so it can fade in on mount. Spans
// are only appended as text grows, so React keeps earlier words mounted and
// each word animates exactly once. Code keeps its exact text.
function rehypeRevealWords({ caret = false } = {}) {
  return tree => {
    let host = null;
    const walk = (node, inCode) => {
      if (!Array.isArray(node.children)) return;
      const next = [];
      for (const child of node.children) {
        if (child.type === "text" && !inCode) {
          for (const part of String(child.value).split(/(\s+)/)) {
            if (!part) continue;
            if (/^\s+$/.test(part)) {
              next.push({ type: "text", value: part });
            } else {
              next.push({ type: "element", tagName: "span", properties: { className: ["nv-w"] }, children: [{ type: "text", value: part }] });
              host = node;
            }
          }
          continue;
        }
        if (child.type === "element") walk(child, inCode || child.tagName === "pre" || child.tagName === "code");
        next.push(child);
      }
      node.children = next;
    };
    walk(tree, false);
    // A distinct tag keeps the caret from taking over a word's React key.
    if (caret && host) {
      host.children.push({ type: "element", tagName: "i", properties: { className: ["nv-caret"], ariaHidden: "true" }, children: [] });
    }
  };
}

// While text is still arriving, hide an unfinished emphasis or inline-code
// marker instead of flashing raw asterisks and backticks.
function stableMarkdown(value) {
  if (((value.match(/```/g) || []).length) % 2 === 1) return value;
  let out = value;
  if (((out.match(/\*\*/g) || []).length) % 2 === 1) out = out.slice(0, out.lastIndexOf("**"));
  if (((out.replace(/```/g, "").match(/`/g) || []).length) % 2 === 1) out = out.slice(0, out.lastIndexOf("`"));
  return out;
}

export default memo(function NeyviaMessageBody({ text, streaming = false, revealKey = "" }) {
  const value = String(text || "");
  const [revealing, setRevealing] = useState(() => (streaming || isLiveMessage(revealKey)) && !prefersReducedMotion());
  // Paint received text immediately; animation may fade new words, but must
  // never queue provider output behind a synthetic typing rate.
  const caughtUp = !streaming;

  useEffect(() => {
    if (streaming && !revealing && !prefersReducedMotion()) setRevealing(true);
  }, [streaming, revealing]);

  useEffect(() => {
    if (!revealing || !caughtUp) return undefined;
    const timer = setTimeout(() => {
      setRevealing(false);
      forgetLiveMessage(revealKey);
    }, FADE_MS);
    return () => clearTimeout(timer);
  }, [revealing, caughtUp, revealKey]);

  const live = revealing && !caughtUp;
  const display = revealing ? stableMarkdown(value) : value;
  const plugins = revealing ? [[rehypeRevealWords, { caret: live }]] : NO_PLUGINS;
  return (
    <div className="neyvia-message-body neyvia-type-voice" data-streaming={live ? "true" : undefined} data-revealing={revealing ? "true" : undefined}>
      <Markdown skipHtml components={components} rehypePlugins={plugins}>{display}</Markdown>
    </div>
  );
});
