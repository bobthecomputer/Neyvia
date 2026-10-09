import { createElement, useId } from "react";
import { describeProviderMark } from "./providerMarkModel.js";
import { PROVIDER_MARKS, providerMarkIds, resolveProviderMarkId } from "./providerMarksData.js";
import "./providerMark.css";

// Sources and licences for every path live in providerMarksData.js (header) and
// PROVIDER_MARKS_SOURCES.md. Import providerMark.css once near the app root if this file
// is not on the import path.
export { PROVIDER_MARKS, providerMarkIds, resolveProviderMarkId };

const CAMEL_EXCEPTIONS = /^(aria|data)-/;

function toReactProps(attrs) {
  const props = {};
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "class") props.className = value;
    else if (CAMEL_EXCEPTIONS.test(name) || !name.includes("-")) props[name] = value;
    else props[name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())] = value;
  }
  return props;
}

function renderNode(node, key) {
  const children = node.text !== undefined ? node.text : (node.children || []).map((child, index) => renderNode(child, index));
  return createElement(node.tag, { ...toReactProps(node.attrs || {}), key }, children);
}

/**
 * Inline vector mark for a provider, agent or integration.
 * Unknown ids render a neutral letter tile. `mono` draws everything in currentColor.
 * Black brand marks (OpenAI, GitHub, Notion...) follow the theme ink, see providerMark.css.
 */
export function ProviderMark({ id, size = 16, title, mono = false, className, ...rest }) {
  const uid = `pm${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const root = describeProviderMark(id, { size, title, mono, className, uid });
  return createElement(root.tag, { ...toReactProps(root.attrs), ...rest }, (root.children || []).map((child, index) => renderNode(child, index)));
}

export default ProviderMark;
